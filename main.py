# --- コードの一番上に追加 ---
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

import os
import datetime
import io
import json  # データ保存用に追加
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import matplotlib.pyplot as plt

# 日本語フォント設定（Linuxサーバー対策）
import matplotlib

matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = [
    "Noto Sans CJK JP",
    "Noto Sans JP",
    "IPAexGothic",
    "DejaVu Sans",
]

load_dotenv()

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# 環境変数から設定を読み込み
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RANK_CHANNEL_ID = int(os.getenv("RANK_CHANNEL_ID"))
TOKEN = os.getenv("DISCORD_TOKEN")

# タイムゾーンを日本時間に固定
JST = datetime.timezone(datetime.timedelta(hours=9))

# 状態記録用（これらは再起動で消えても大きな問題はないもの）
join_times = {}

# ============================================
# 💾 データの永続化（再起動対策）
# ============================================
DATA_FILE = "vc_data.json"


def load_data():
    """ファイルからデータを読み込む"""
    global total_times, monthly_times
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
                total_times = {int(k): v for k, v in saved_data.get("total", {}).items()}
                # jsonはキーが文字列になるため、intや年月に復元する
                raw_monthly = saved_data.get("monthly", {})
                monthly_times = {}
                for y_str, months in raw_monthly.items():
                    monthly_times[int(y_str)] = {}
                    for m_str, users in months.items():
                        monthly_times[int(y_str)][int(m_str)] = {
                            int(uid): sec for uid, sec in users.items()
                        }
                print("データをファイルから読み込みました。")
                return
        except Exception as e:
            print(f"データ読み込みエラー: {e}")

    total_times = {}
    monthly_times = {}


def save_data():
    """データをファイルに保存する"""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"total": total_times, "monthly": monthly_times}, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"データ保存エラー: {e}")


# 最初にデータを読み込む
load_data()


# ============================================
# Bot起動
# ============================================
@bot.event
async def on_ready():
    print(f"ログインしました: {bot.user}")
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        pass

    # タスクが既に動いていないか確認して起動
    if not auto_monthly_report.is_running():
        auto_monthly_report.start()

    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンド同期完了: {len(synced)}個")
    except Exception as e:
        print(e)


# ============================================
# VC参加・退出イベント
# ============================================
@bot.event
async def on_voice_state_update(member, before, after):
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    # 参加
    if before.channel is None and after.channel is not None:
        join_times[member.id] = datetime.datetime.now(JST)  # 日本時間

        embed = discord.Embed(
            description=f"🟢 **{member.display_name}** が **{after.channel.name}** に参加しました",
            color=discord.Color.green(),
        )
        await channel.send(embed=embed)

    # 退出
    elif before.channel is not None and after.channel is None:
        start = join_times.get(member.id)

        if start:
            end = datetime.datetime.now(JST)  # 日本時間
            duration = end - start
            seconds = int(duration.total_seconds())

            # 累計時間
            total_times[member.id] = total_times.get(member.id, 0) + seconds

            # 月別時間
            year = end.year
            month = end.month

            if year not in monthly_times:
                monthly_times[year] = {}
            if month not in monthly_times[year]:
                monthly_times[year][month] = {}

            monthly_times[year][month][member.id] = (
                monthly_times[year][month].get(member.id, 0) + seconds
            )

            # 💡 退出が記録されたらファイルに保存する
            save_data()

            minutes = seconds // 60
            sec = seconds % 60

            if minutes >= 60:
                color = discord.Color.red()
            elif minutes >= 30:
                color = discord.Color.orange()
            else:
                color = discord.Color.blue()

            embed = discord.Embed(
                title="通話終了",
                description=f"🔴 **{member.display_name}** が **{before.channel.name}** から退出しました",
                color=color,
            )
            embed.add_field(name="今回の通話時間", value=f"**{minutes}分 {sec}秒**", inline=False)

            total_min = total_times[member.id] // 60
            total_sec = total_times[member.id] % 60
            embed.add_field(name="累計通話時間", value=f"**{total_min}分 {total_sec}秒**", inline=False)

            await channel.send(embed=embed)
            join_times.pop(member.id, None)

        else:
            embed = discord.Embed(
                description=f"🔴 **{member.display_name}** が **{before.channel.name}** から退出しました",
                color=discord.Color.red(),
            )
            await channel.send(embed=embed)

    # 移動
    elif before.channel.id != after.channel.id:
        embed = discord.Embed(
            description=f"🟡 **{member.display_name}** が **{before.channel.name}** → **{after.channel.name}** に移動しました",
            color=discord.Color.yellow(),
        )
        await channel.send(embed=embed)


# ============================================
# ランキング投稿関数
# ============================================
async def post_monthly_rank(channel, year, month, is_progress=False):
    if year not in monthly_times or month not in monthly_times[year]:
        await channel.send(f"{year}年{month}月の通話記録はありません。")
        return

    data = monthly_times[year][month]
    ranking = sorted(data.items(), key=lambda x: x[1], reverse=True)

    title = (
        f"📅 {year}年{month}月 通話時間ランキング（途中経過）"
        if is_progress
        else f"🎖 {year}年{month}月 通話時間ランキング（確定）"
    )

    embed = discord.Embed(title=title, color=discord.Color.gold())
    medals = ["🥇", "🥈", "🥉"]

    for i, (user_id, sec) in enumerate(ranking, start=1):
        member = channel.guild.get_member(user_id)
        if member:
            hours = sec // 3600
            minutes = (sec % 3600) // 60
            seconds = sec % 60

            time_text = (
                f"{hours}時間 {minutes}分 {seconds}秒" if hours > 0 else f"{minutes}分 {seconds}秒"
            )
            icon = medals[i - 1] if i <= 3 else f"{i}位 🔹"

            embed.add_field(name=f"{icon} {member.display_name}", value=f"**{time_text}**", inline=False)

    await channel.send(embed=embed)


# ============================================
# 自動投稿タスク（日本時間基準に修正）
# ============================================
@tasks.loop(minutes=1)
async def auto_monthly_report():
    now = datetime.datetime.now(JST)  # 日本時間
    rank_channel = bot.get_channel(RANK_CHANNEL_ID)
    if not rank_channel:
        return

    # 毎月1日 00:00 → 先月のランキング
    if now.day == 1 and now.hour == 0 and now.minute == 0:
        year = now.year
        month = now.month - 1
        if month == 0:
            year -= 1
            month = 12
        await post_monthly_rank(rank_channel, year, month)

    # 毎月10日・20日・30日 → 途中経過
    if now.day in [10, 20, 30] and now.hour == 0 and now.minute == 0:
        await post_monthly_rank(rank_channel, now.year, now.month, is_progress=True)


@auto_monthly_report.before_loop
async def before_auto_monthly_report():
    await bot.wait_until_ready()


# ============================================
# スラッシュコマンド
# ============================================
@bot.tree.command(name="vcrank_month", description="指定した月の通話時間ランキングを表示します")
async def vcrank_month_slash(interaction: discord.Interaction, year: int = None, month: int = None):
    now = datetime.datetime.now(JST)
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    rank_channel = interaction.guild.get_channel(RANK_CHANNEL_ID)
    if rank_channel:
        await post_monthly_rank(rank_channel, year, month)
        await interaction.response.send_message("ランキングを投稿しました！", ephemeral=True)
    else:
        await interaction.response.send_message("チャンネルが見つかりません。", ephemeral=True)


@bot.tree.command(name="vcrank_progress", description="今月の途中経過ランキングを表示します")
async def vcrank_progress_slash(interaction: discord.Interaction):
    now = datetime.datetime.now(JST)
    rank_channel = interaction.guild.get_channel(RANK_CHANNEL_ID)
    if rank_channel:
        await post_monthly_rank(rank_channel, now.year, now.month, is_progress=True)
        await interaction.response.send_message("途中経過を投稿しました！", ephemeral=True)
    else:
        await interaction.response.send_message("チャンネルが見つかりません。", ephemeral=True)


@bot.tree.command(name="vcrank_graph", description="今月の通話時間ランキングをグラフで表示します")
async def vcrank_graph_slash(interaction: discord.Interaction):
    now = datetime.datetime.now(JST)
    year = now.year
    month = now.month

    if year not in monthly_times or month not in monthly_times[year]:
        await interaction.response.send_message("今月の通話記録はまだありません。")
        return

    # 遅延対策の応答
    await interaction.response.defer()

    data = monthly_times[year][month]
    ranking = sorted(data.items(), key=lambda x: x[1], reverse=True)

    names = []
    hours_list = []

    for user_id, sec in ranking:
        member = interaction.guild.get_member(user_id)
        if member:
            hours = sec / 3600
            names.append(member.display_name)
            hours_list.append(hours)

    if not names:
        await interaction.followup.send("グラフに表示できるメンバーがサーバー内に見つかりません。")
        return

    plt.figure(figsize=(10, 6))
    plt.barh(names, hours_list, color="skyblue")
    plt.xlabel("通話時間（時間）")
    plt.title(f"{year}年{month}月 通話時間ランキング（グラフ）")
    plt.gca().invert_yaxis()
    plt.tight_layout()  # 文字切れ対策

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close()

    file = discord.File(buf, filename="vcrank_graph.png")
    await interaction.followup.send(file=file)
# --- コードの一番下（bot.run の手前）に追加 ---
keep_alive()
bot.run(TOKEN)

