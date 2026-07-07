import discord
from discord.ext import commands, tasks
import random
import asyncio
import json
import os
import time
from flask import Flask
import threading

# --- 🌐 Webサーバー ---
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

race_bets = {}
horses = {1: "🐴ドロボウキング", 2: "🐴オマモリマル", 3: "🐴チンチロマスター", 4: "🐴コゼニデント"}
DATA_FILE = "data.json"
user_data = {}

# --- 🛠️ 共通関数 ---
async def update_nickname(member: discord.Member, coins: int):
    try:
        original_name = member.display_name.split('：')[0]
        new_nick = f"{original_name}：{coins}コイン"
        if len(new_nick) <= 32: await member.edit(nick=new_nick)
    except: pass

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

# --- 🎤 通話報酬 ---
@tasks.loop(minutes=1.0)
async def income_timer():
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if not member.bot:
                    p = get_user_profile(member.id)
                    p["coins"] += 10
                    await update_nickname(member, p["coins"])
    save_data()

@bot.event
async def on_ready():
    await bot.tree.sync()
    load_data()
    income_timer.start()
    
    # 【追加】起動時に通話中の全員を検知して開始時間を記録する
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if not member.bot:
                    call_start_times[member.id] = time.time()
    
    print(f"✅ 起動完了！")

# --- 🎮 コマンド ---

@bot.tree.command(name="wallet", description="所持金と持ち物を自分だけ確認")
async def wallet(interaction: discord.Interaction):
    p = get_user_profile(interaction.user.id)
    msg = f"💰 所持金: {p['coins']}コイン\n🎫 チケット: {p['tickets']}枚\n🛡️ お守り: {p['shields']}個"
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="gacha", description="ガチャ")
async def gacha(interaction: discord.Interaction):
    p = get_user_profile(interaction.user.id)
    if p["coins"] < 100: return await interaction.response.send_message("❌ コイン不足", ephemeral=True)
    
    p["coins"] -= 100
    roll = random.randint(1, 100)
    
    # 48:20:32 のバランス設定
    if roll <= 48:
        win = random.randint(50, 300)
        p["coins"] += win
        res = f"🎉 {win}コイン"
    elif roll <= 68: # 48 + 20 = 68
        p["shields"] += 1
        res = "🛡️ お守り"
    else: # 残り32
        p["tickets"] += 1
        res = "🎫 泥棒チケット"
        
    save_data()
    await update_nickname(interaction.user, p["coins"])
    await interaction.response.send_message(f"🎰 結果: {res} をゲット！", ephemeral=True)

@bot.tree.command(name="steal", description="泥棒")
async def steal(interaction: discord.Interaction, target: discord.Member):
    p, t = get_user_profile(interaction.user.id), get_user_profile(target.id)
    if p["tickets"] < 1: return await interaction.response.send_message("❌ チケット不足", ephemeral=True)
    p["tickets"] -= 1
    stolen = random.randint(50, 200)
    t["coins"] -= stolen; p["coins"] += stolen
    save_data()
    await update_nickname(interaction.user, p["coins"])
    await update_nickname(target, t["coins"])
    await interaction.response.send_message(f"🦹 {stolen}コイン奪った", ephemeral=True)

@bot.tree.command(name="chinchiro", description="チンチロ")
async def chinchiro(interaction: discord.Interaction, bet: int):
    p = get_user_profile(interaction.user.id)
    if p["coins"] < bet: return await interaction.response.send_message("❌ 不足", ephemeral=True)
    p["coins"] += random.choice([-bet, bet])
    save_data()
    await update_nickname(interaction.user, p["coins"])
    await interaction.response.send_message(f"🎲 決着！", ephemeral=True)

@bot.tree.command(name="race_bet", description="競馬")
async def race_bet(interaction: discord.Interaction, horse_num: int, bet: int):
    cid = interaction.channel.id
    if cid not in race_bets: race_bets[cid] = {}
    p = get_user_profile(interaction.user.id)
    if p["coins"] < bet: return await interaction.response.send_message("❌ 不足", ephemeral=True)
    p["coins"] -= bet; race_bets[cid][interaction.user.id] = {"horse": horse_num, "bet": bet}
    save_data()
    await update_nickname(interaction.user, p["coins"])
    await interaction.response.send_message(f"🏁 {horses[horse_num]} に賭けました", ephemeral=True)

@bot.tree.command(name="race_start", description="レース開始")
async def race_start(interaction: discord.Interaction):
    cid = interaction.channel.id
    if not race_bets.get(cid): return await interaction.response.send_message("❌ 誰も賭けていません", ephemeral=True)
    
    total_pool = sum(b['bet'] for b in race_bets[cid].values())
    horse_bets = {1:0, 2:0, 3:0, 4:0}
    for b in race_bets[cid].values(): horse_bets[b['horse']] += b['bet']
    
    odds_text = "\n".join([f"{horses[h]}: {round(total_pool/pool, 1) if pool>0 else 0}倍" for h, pool in horse_bets.items()])
    await interaction.response.send_message(f"🟢 レース開始！\n【オッズ】\n{odds_text}")
    msg = await interaction.followup.send("🏁 実況: レースが始まりました！")
    
    progress = {1:0, 2:0, 3:0, 4:0}
    for _ in range(15):
        await asyncio.sleep(1.0)
        for h in progress: progress[h] += random.randint(0, 3)
        await msg.edit(content=f"🏁 実況中...\n" + "\n".join([f"{horses[h]}: {'・'*progress[h]}🏇" for h in progress]))
    
    winner = max(progress, key=progress.get)
    await interaction.followup.send(f"👑 優勝は {horses[winner]}！")
    
    for u_id, b in race_bets[cid].items():
        if b["horse"] == winner: 
            p = get_user_profile(u_id)
            p["coins"] += int(b["bet"] * (total_pool / horse_bets[winner]))
            m = interaction.guild.get_member(u_id)
            if m: await update_nickname(m, p["coins"])
    race_bets[cid] = {}; save_data()

bot.run(os.getenv("DISCORD_TOKEN"))