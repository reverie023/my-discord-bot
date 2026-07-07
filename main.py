import discord
from discord.ext import commands, tasks
import random
import asyncio
import json
import os
import time

# ボットの初期設定
intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents)

# 【チャンネル名の設定】Discordのチャンネル名と一致させてください
CHANNEL_GACHA = "ガチャ"
CHANNEL_GAMBLE = "賭け場"
CHANNEL_STATUS = "ステータス"
CHANNEL_CALL_LOG = "通話履歴"

# --- 💾 データセーブ・ロードシステム ---
DATA_FILE = "data.json"
user_data = {}

# ⏱️ 通話時間を記録する一時メモリ
call_start_times = {}

def load_data():
    global user_data
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                user_data = json.load(f)
                print("💾 ユーザーデータをファイルから読み込みました。")
        except Exception as e:
            print(f"⚠️ データ読み込みエラー: {e}")
            user_data = {}

def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(user_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"⚠️ データ保存エラー: {e}")

def get_user_profile(user_id):
    uid_str = str(user_id)
    if uid_str not in user_data:
        user_data[uid_str] = {"coins": 0, "tickets": 0, "shields": 0}
        save_data()
    return user_data[uid_str]

# 【チャンネル制限チェック】
async def check_channel(ctx, target_channel_name):
    if ctx.channel.name == target_channel_name:
        return True
    msg = await ctx.send(f"❌ このコマンドは **#{target_channel_name}** チャンネル専用です！")
    await asyncio.sleep(3)
    try:
        await ctx.message.delete()
        await msg.delete()
    except:
        pass
    return False

# ログ送信ヘルパー
async def send_call_log(guild, text):
    channel = discord.utils.get(guild.text_channels, name=CHANNEL_CALL_LOG)
    if channel:
        await channel.send(text)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    load_data()
    reset_race()
    
    # 💡 ボット起動時にすでに通話にいる人を救済（起動した瞬間からカウント）
    now = time.time()
    for guild in bot.guilds:
        for voice_channel in guild.voice_channels:
            for member in voice_channel.members:
                if not member.bot:
                    call_start_times[member.id] = now
                    # 起動時入室の最低保証10コイン
                    profile = get_user_profile(member.id)
                    profile["coins"] += 10
    save_data()
    
    income_timer.start()

# --- 🪙 通話報酬システム (1分ごとに裏で10コイン追加、通知はなし) ---
@tasks.loop(minutes=1.0)
async def income_timer():
    updated = False
    for guild in bot.guilds:
        for voice_channel in guild.voice_channels:
            for member in voice_channel.members:
                if member.bot:
                    continue
                profile = get_user_profile(member.id)
                profile["coins"] += 10
                updated = True
    if updated:
        save_data()

# --- 🎤 ボイスチャンネル監視（通話終了時のみログを出す） ---
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    # パターン1: 通話に参加したとき（裏で時間記録と最低保証のみ）
    if before.channel is None and after.channel is not None:
        profile = get_user_profile(member.id)
        profile["coins"] += 10
        save_data()
        call_start_times[member.id] = time.time()

    # パターン2: 通話を完全に終了（退出）したとき 💡ここで初めてログを出す
    elif before.channel is not None and after.channel is None:
        start_time = call_start_times.pop(member.id, None)
        
        if start_time is not None:
            duration_seconds = time.time() - start_time
            duration_minutes = int(duration_seconds // 60)
            earned_coins = (duration_minutes * 10) + 10
            
            await send_call_log(
                member.guild, 
                f"📴 【通話終了】 **{member.display_name}** が「{before.channel.name}」から退出しました。\n"
                f"⏱️ 通話時間: 約 **{duration_minutes}分** / 🪙 合計獲得: **+{earned_coins}コイン**"
            )

# --- 💳 コマンド: お財布確認 (ステータス専用) ---
@bot.command(name="wallet")
async def wallet(ctx):
    if not await check_channel(ctx, CHANNEL_STATUS): return
    profile = get_user_profile(ctx.author.id)
    embed = discord.Embed(title="💰 あなたの財布・インベントリ", color=0xffd700)
    embed.add_field(name="🪙 所持コイン", value=f"**{profile['coins']}** コイン", inline=False)
    embed.add_field(name="🎫 泥棒チケット", value=f"**{profile['tickets']}** 枚", inline=True)
    embed.add_field(name="🛡️ お守りカード", value=f"**{profile['shields']}** 枚", inline=True)
    await ctx.send(embed=embed)

# --- 🎰 コマンド: ガチャ (ガチャ専用) ---
@bot.command(name="gacha")
async def gacha(ctx):
    if not await check_channel(ctx, CHANNEL_GACHA): return
    profile = get_user_profile(ctx.author.id)
    gacha_cost = 100
    
    if profile["coins"] < gacha_cost:
        await ctx.send(f"❌ コインが足りません！（ガチャ1回: {gacha_cost}コイン）")
        return
    
    profile["coins"] -= gacha_cost
    roll = random.randint(1, 100)
    
    if roll <= 40:
        sub_roll = random.randint(1, 100)
        tickets_won = 1 if sub_roll <= 55 else (2 if sub_roll <= 80 else 3)
        profile["tickets"] += tickets_won
        result_text = f"🎫 **泥棒チケット が {tickets_won}枚** 当たった！\n`/steal [相手]` コマンドで使えます！"
        color = 0x3498db
    elif roll <= 90:
        coins_won = random.randint(30, 120)
        profile["coins"] += coins_won
        result_text = f"🪙 **小銭ゲット！**\nお財布に **{coins_won}コイン** がプラスされました！"
        color = 0x2ecc71
    else:
        profile["shields"] += 1
        result_text = f"🛡️ **お守りカード（レア）** が当たった！\n泥棒を1回自動でガードします！"
        color = 0xe74c3c

    save_data()
    embed = discord.Embed(title="🎰 ガチャ結果", description=result_text, color=color)
    await ctx.send(embed=embed)

# --- 🦹 コマンド: 泥棒 (ガチャ専用) ---
@bot.command(name="steal")
async def steal(ctx, target: discord.Member):
    if not await check_channel(ctx, CHANNEL_GACHA): return
    thief = ctx.author
    thief_profile = get_user_profile(thief.id)
    target_profile = get_user_profile(target.id)
    
    if thief.id == target.id or target.bot:
        await ctx.send("❌ 対象が不正です。")
        return
    if thief_profile["tickets"] < 1:
        await ctx.send("❌ 泥棒チケットを持っていません！")
        return
    
    thief_profile["tickets"] -= 1
    try: await ctx.message.delete()
    except: pass

    if target_profile["shields"] > 0:
        target_profile["shields"] -= 1
        save_data()
        try: await thief.send(f"💀 **泥棒失敗…**\n{target.display_name} はお守りを持っていました！")
        except: pass
        try: await target.send(f"🛡️ **ガード成功！**\n誰かの泥棒をお守りカードで防ぎました！")
        except: pass
        return

    steal_roll = random.randint(1, 100)
    if steal_roll <= 10: stolen_coins, r_type = 300, "🔥 **大成功！！**"
    elif steal_roll <= 40: stolen_coins, r_type = 200, "✨ **中成功！**"
    elif steal_roll <= 90: stolen_coins, r_type = 100, "👍 **小成功**"
    else: stolen_coins, r_type = 0, "💀 **失敗…**"

    if target_profile["coins"] < stolen_coins:
        stolen_coins = target_profile["coins"]

    target_profile["coins"] -= stolen_coins
    thief_profile["coins"] += stolen_coins
    save_data()

    try: await thief.send(f"{r_type}\n{target.display_name} から **{stolen_coins}コイン** 奪いました！" if stolen_coins > 0 else f"{r_type}\n何も盗めませんでした…")
    except: pass
    if stolen_coins > 0:
        try: await target.send(f"🚨 **警告：泥棒被害！**\n誰かに **{stolen_coins}コイン** 盗まれました！")
        except: pass

# --- 🎲 ゲーム1: ちんちろ (賭け場専用) ---
def get_chinchiro_eye():
    dice = [random.randint(1, 6) for _ in range(3)]
    dice.sort()
    if dice == [1, 1, 1]: return (5, "ピンゾロ (5倍返し)")
    if dice[0] == dice[1] == dice[2]: return (3, f"{dice[0]}のゾロ目 (3倍返し)")
    if dice == [4, 5, 6]: return (3, "シゴロ (3倍返し)")
    if dice == [1, 2, 3]: return (0, "ヒフミ (即負け)")
    if dice[0] == dice[1]: return (1, f"目:{dice[2]}")
    if dice[1] == dice[2]: return (1, f"目:{dice[0]}")
    return (0, "目なし")

@bot.command(name="chinchiro")
async def chinchiro(ctx, bet: int):
    if not await check_channel(ctx, CHANNEL_GAMBLE): return
    profile = get_user_profile(ctx.author.id)
    if bet < 10 or bet > 500:
        await ctx.send("❌ 賭け金は 10 〜 500 コインの間で指定してください。")
        return
    if profile["coins"] < bet:
        await ctx.send("❌ 所持コインが足りません。")
        return

    profile["coins"] -= bet
    save_data()
    
    p_mult, p_name = get_chinchiro_eye()
    await ctx.send(f"🎲 {ctx.author.mention} の出目: **{p_name}**")
    await asyncio.sleep(1)
    
    b_mult, b_name = get_chinchiro_eye()
    await ctx.send(f"🤖 ボット（親）の出目: **{b_name}**")
    await asyncio.sleep(1)
    
    if p_name == "ヒフミ (即負け)":
        await ctx.send(f"😭 {ctx.author.mention} の負け！ **{bet}コイン** 没収。")
    elif b_name == "ヒフミ (即負け)" and p_name != "目なし":
        p_mult = max(p_mult, 1)
        reward = bet * (p_mult + 1)
        profile["coins"] += reward
        await ctx.send(f"🎉 ボットが自滅！{ctx.author.mention} の勝ち！ **+{reward - bet}コイン**")
    elif p_mult > b_mult or (p_mult == b_mult and p_mult > 0 and p_name > b_name):
        reward = bet * (p_mult + 1)
        profile["coins"] += reward
        await ctx.send(f"🎉 {ctx.author.mention} の勝ち！ **+{reward - bet}コイン**")
    elif p_mult == b_mult and p_name == b_name and p_name != "目なし":
        profile["coins"] += bet
        await ctx.send("🤝 引き分け！コインが戻ってきました。")
    else:
        await ctx.send(f"😭 {ctx.author.mention} の負け！ **{bet}コイン** 没収。")
    
    save_data()

# --- 🐴 ゲーム2: カジノ競馬 (賭け場専用) ---
horses = {1: "🐴ドロボウキング", 2: "🐴オマモリマル", 3: "🐴チンチロマスター", 4: "🐴コゼニデント"}
horse_odds = {1: 4.0, 2: 4.0, 3: 4.0, 4: 4.0}
race_bets = {}
race_active = False

def reset_race():
    global horse_odds, race_bets
    race_bets.clear()
    for i in range(1, 5):
        horse_odds[i] = round(random.uniform(1.5, 9.5), 1)

@bot.command(name="race_bet")
async def race_bet(ctx, horse_num: int, bet: int):
    if not await check_channel(ctx, CHANNEL_GAMBLE): return
    global race_active
    if race_active:
        await ctx.send("❌ すでにレースが発走しています！")
        return
    if horse_num not in horses:
        await ctx.send("❌ 1〜4番のウマを選んでください。")
        return
    if bet < 10 or bet > 500:
        await ctx.send("❌ 賭け金は 10 〜 500 コインの間です。")
        return
    
    profile = get_user_profile(ctx.author.id)
    if profile["coins"] < bet:
        await ctx.send("❌ コインが足りません。")
        return
        
    profile["coins"] -= bet
    save_data()
    
    race_bets[ctx.author.id] = {
        "horse": horse_num, 
        "bet": bet, 
        "odds": horse_odds[horse_num],
        "name": ctx.author.display_name
    }
    
    odds_info = "\n".join([f"{horses[i]} : **{horse_odds[i]}倍**" for i in range(1, 5)])
    await ctx.send(
        f"🏁 {ctx.author.mention} が **{horses[horse_num]}** ({horse_odds[horse_num]}倍) に **{bet}コイン** 賭けました！\n\n"
        f"【現在の出走馬・オッズ】\n{odds_info}\n\n"
        f"`/race_start` でスタート！"
    )

@bot.command(name="race_start")
async def race_start(ctx):
    if not await check_channel(ctx, CHANNEL_GAMBLE): return
    global race_active, race_bets
    if race_active: return
    if not race_bets:
        await ctx.send("❌ 誰もウマに賭けていません！")
        return
        
    race_active = True
    progress = {1: 0, 2: 0, 3: 0, 4: 0}
    goal = 15
    
    msg = await ctx.send("🟢 各馬一斉にスタートしました！！\n" + "\n".join([f"{horses[i]}: 「」" for i in range(1, 5)]))
    await asyncio.sleep(1.5)
    
    while max(progress.values()) < goal:
        for i in range(1, 5):
            speed_bonus = 1 if horse_odds[i] < 3.5 else 0
            progress[i] += random.randint(1, 3) + speed_bonus
        
        lines = []
        for i in range(1, 5):
            lane = "・" * progress[i] + "🏇" + "・" * max(0, (goal - progress[i]))
            if progress[i] >= goal: lane = " " * goal + "✨👑✨"
            lines.append(f"{horses[i]}: 「{lane}」")
            
        await msg.edit(content="🏁 **レース実況中！！** 🏁\n" + "\n".join(lines))
        await asyncio.sleep(1.2)
        
    winner = max(progress, key=progress.get)
    await ctx.send(f"👑 1着は **{horses[winner]}** です！！！")
    
    payout_messages = []
    for u_id, b_info in race_bets.items():
        if b_info["horse"] == winner:
            reward = int(b_info["bet"] * b_info["odds"])
            get_user_profile(u_id)["coins"] += reward
            payout_messages.append(f"🎉 {b_info['name']} が的中！ (倍率: {b_info['odds']}倍) **+{reward}コイン**")
            
    if payout_messages:
        await ctx.send("\n".join(payout_messages))
    else:
        await ctx.send("💸 的中者は誰もいませんでした…")
        
    save_data()
    reset_race()
    race_active = False

# --- ⚙️ Render用環境変数読み込み部（修正済） ---
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ 環境変数 'DISCORD_TOKEN' が設定されていません！")