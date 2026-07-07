import discord
from discord import app_commands
from discord.ext import commands, tasks
import random
import asyncio
import json
import os
import time
from flask import Flask
import threading

# --- 🌐 Webサーバー (24時間稼働用) ---
app = Flask('')
@app.route('/')
def home(): return "Bot is alive!"
threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.getenv("PORT", 10000))), daemon=True).start()

# --- 🤖 初期設定 ---
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

# チャンネル設定と管理用データ
CHANNELS = {"GACHA": "ガチャ", "GAMBLE": "賭け場", "STATUS": "ステータス", "LOG": "通話履歴"}
lobby, race_bets, call_start_times = {}, {}, {}
horses = {1: "🐴ドロボウキング", 2: "🐴オマモリマル", 3: "🐴チンチロマスター", 4: "🐴コゼニデント"}

# --- 💾 データ管理 ---
DATA_FILE = "data.json"
user_data = {}

# --- ニックネーム更新関数 ---
async def update_nickname(member: discord.Member, coins: int):
    try:
        # 元の名前（ニックネーム）を取得して、「：」の前の部分だけを取り出す
        # すでに「名前：コイン」となっている場合は「名前」だけを抽出する処理
        original_name = member.display_name.split('：')[0]
        
        # 名前と所持金を合体させる
        new_nick = f"{original_name}：{coins}コイン"
        
        # ニックネームの長さが32文字以内なら更新
        if len(new_nick) <= 32:
            await member.edit(nick=new_nick)
    except discord.Forbidden:
        print(f"❌ {member.name} の名前を変更する権限がありません。")

def load_data():
    global user_data
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            user_data = json.load(f)

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(user_data, f, ensure_ascii=False, indent=4)

def get_user_profile(user_id):
    uid_str = str(user_id)
    if uid_str not in user_data:
        user_data[uid_str] = {"coins": 1000, "tickets": 0, "shields": 0}
        save_data()
    return user_data[uid_str]

# --- 🛡️ チャンネル制限チェック ---
async def check_channel(interaction: discord.Interaction, target_name):
    if interaction.channel.name != target_name:
        await interaction.response.send_message(f"❌ このコマンドは **#{target_name}** で実行してください！", ephemeral=True)
        return False
    return True

# --- 🎤 通話報酬システム ---
@tasks.loop(minutes=1.0)
async def income_timer():
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if not member.bot:
                    get_user_profile(member.id)["coins"] += 10
    save_data()

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    if before.channel is None and after.channel is not None:
        call_start_times[member.id] = time.time()
    elif before.channel is not None and after.channel is None:
        start_time = call_start_times.pop(member.id, None)
        if start_time:
            dur = int((time.time() - start_time) // 60)
            log_ch = discord.utils.get(member.guild.text_channels, name=CHANNELS["LOG"])
            if log_ch:
                await log_ch.send(f"📴 **{member.display_name}** が退出。通話時間: 約{dur}分。獲得コイン: +{(dur*10)+10}")

@bot.event
async def on_ready():
    await bot.tree.sync()
    load_data()
    income_timer.start()
    print(f"✅ {bot.user.name} 起動完了！")

# --- 🎮 ゲームコマンド ---
@bot.tree.command(name="join", description="待機室に参加")
async def join(interaction: discord.Interaction):
    cid = interaction.channel.id
    if cid not in lobby: lobby[cid] = {"players": []}
    if interaction.user.id not in lobby[cid]["players"]:
        lobby[cid]["players"].append(interaction.user.id)
        await interaction.response.send_message("✅ 参加しました！")
    else: await interaction.response.send_message("❌ 参加済みです。")

@bot.tree.command(name="wallet", description="所持金確認")
async def wallet(interaction: discord.Interaction):
    if not await check_channel(interaction, CHANNELS["STATUS"]): return
    p = get_user_profile(interaction.user.id)
    await interaction.response.send_message(f"💰 {p['coins']}コイン / 🎫 {p['tickets']}枚 / 🛡️ {p['shields']}個")

@bot.tree.command(name="gacha", description="ガチャ")
async def gacha(interaction: discord.Interaction):
    if not await check_channel(interaction, CHANNELS["GACHA"]): return
    p = get_user_profile(interaction.user.id)
    if p["coins"] < 100: 
        # ここも自分だけに通知
        return await interaction.response.send_message("❌ コインが足りません！", ephemeral=True)
    
    p["coins"] -= 100
    if random.randint(1, 100) <= 90: 
        p["coins"] += random.randint(30, 120); res = "コイン"
    else: 
        p["shields"] += 1; res = "お守り"
        
    save_data()
    await update_nickname(interaction.user, p["coins"])
    
    # ★ここを修正: ephemeral=True を追加
    await interaction.response.send_message(f"🎰 結果: {res} をゲットしました！", ephemeral=True)

@bot.tree.command(name="steal", description="泥棒")
async def steal(interaction: discord.Interaction, target: discord.Member):
    if not await check_channel(interaction, CHANNELS["GACHA"]): return
    p, t = get_user_profile(interaction.user.id), get_user_profile(target.id)
    if p["tickets"] < 1: return await interaction.response.send_message("❌ チケット不足")
    p["tickets"] -= 1
    if t["shields"] > 0: t["shields"] -= 1; await interaction.response.send_message("🛡️ ガード成功")
    else: stolen = random.randint(50, 200); t["coins"] -= stolen; p["coins"] += stolen; await interaction.response.send_message(f"🦹 {stolen}コイン奪った")
    save_data()

@bot.tree.command(name="chinchiro", description="チンチロ")
async def chinchiro(interaction: discord.Interaction, bet: int):
    if not await check_channel(interaction, CHANNELS["GAMBLE"]): return
    p = get_user_profile(interaction.user.id)
    if p["coins"] < bet: return await interaction.response.send_message("❌ コイン不足")
    dice = sorted([random.randint(1, 6) for _ in range(3)])
    p["coins"] += random.choice([-bet, bet])
    save_data(); await interaction.response.send_message(f"🎲 出目: {dice}")

@bot.tree.command(name="race_bet", description="競馬に賭ける")
async def race_bet(interaction: discord.Interaction, horse_num: int, bet: int):
    if not await check_channel(interaction, CHANNELS["GAMBLE"]): return
    cid = interaction.channel.id
    if cid not in race_bets: race_bets[cid] = {}
    p = get_user_profile(interaction.user.id)
    if p["coins"] < bet: return await interaction.response.send_message("❌ コイン不足")
    p["coins"] -= bet; race_bets[cid][interaction.user.id] = {"horse": horse_num, "bet": bet}
    save_data(); await interaction.response.send_message(f"🏁 {horses[horse_num]} に {bet}コイン賭け！")

@bot.tree.command(name="race_start", description="レース開始")
async def race_start(interaction: discord.Interaction):
    if not await check_channel(interaction, CHANNELS["GAMBLE"]): return
    cid = interaction.channel.id
    if cid not in race_bets or not race_bets[cid]: return await interaction.response.send_message("❌ 誰も賭けていません")
    await interaction.response.send_message("🟢 レーススタート！！")
    msg = await interaction.followup.send("🏁 実況中...")
    progress = {1: 0, 2: 0, 3: 0, 4: 0}
    for _ in range(15):
        await asyncio.sleep(0.5)
        for i in range(1, 5): progress[i] += random.randint(0, 2)
        await msg.edit(content="\n".join([f"{horses[i]}: {'・'*progress[i]}🏇" for i in range(1, 5)]))
    winner = max(progress, key=progress.get)
    await interaction.followup.send(f"👑 優勝は {horses[winner]}！")
    for u_id, b in race_bets[cid].items():
        if b["horse"] == winner: get_user_profile(u_id)["coins"] += b["bet"] * 3
    race_bets[cid] = {}; save_data()

bot.run(os.getenv("DISCORD_TOKEN"))