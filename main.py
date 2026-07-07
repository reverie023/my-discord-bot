import discord
from discord.ext import import commands, tasks
from discord import app_commands  # ★この行を新しく追加しました！
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

CHANNELS = {"GACHA": "ガチャ", "GAMBLE": "賭け場", "STATUS": "ステータス", "LOG": "通話履歴"}
race_bets = {}
call_start_times = {}
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

# チャンネル制限チェック関数
async def check_channel(interaction: discord.Interaction, target_key):
    target_name = CHANNELS[target_key]
    if interaction.channel.name != target_name:
        await interaction.response.send_message(f"❌ このコマンドは **#{target_name}** で実行してください！", ephemeral=True)
        return False
    return True

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
    
    # 起動時に通話中のメンバーを検知
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                # メンバーがNoneだったり、botだったりする場合を考慮して安全に記録
                if member and not member.bot:
                    call_start_times[member.id] = time.time()
    
    print(f"✅ 起動完了！")

# --- 🎮 コマンド ---

@bot.tree.command(name="wallet", description="所持金確認")
async def wallet(interaction: discord.Interaction):
    if not await check_channel(interaction, "STATUS"): return
    p = get_user_profile(interaction.user.id)
    await interaction.response.send_message(f"💰 所持金: {p['coins']}コイン\n🎫 チケット: {p['tickets']}枚\n🛡️ お守り: {p['shields']}個", ephemeral=True)

@bot.tree.command(name="gacha", description="ガチャ")
async def gacha(interaction: discord.Interaction):
    if not await check_channel(interaction, "GACHA"): return
    p = get_user_profile(interaction.user.id)
    if p["coins"] < 100: return await interaction.response.send_message("❌ コイン不足", ephemeral=True)
    
    p["coins"] -= 100
    roll = random.randint(1, 100)
    
    # 🎰 新排出率: コイン 50% : ハズレ 35% : アイテム 15%
    if roll <= 50:
        # コイン当選の中の判定（2%で超大当たり）
        if random.randint(1, 100) <= 2:
            win = random.randint(2300, 2500)
            res = f"💎✨ 超超超大当たり！ {win}コイン"
        else:
            win = random.randint(50, 400)
            res = f"🎉 {win}コイン"
        p["coins"] += win
        
    elif roll <= 85: # 50 + 35 = 85
        # 35%でハズレ
        res = "💨 ハズレ"
    else:
        # 残り15%でアイテム（お守りかチケット）
        item_type = random.choice(["お守り", "泥棒チケット"])
        if item_type == "お守り":
            p["shields"] += 1
            res = "🛡️ お守り"
        else:
            p["tickets"] += 1
            res = "🎫 泥棒チケット"
        
    save_data()
    await update_nickname(interaction.user, p["coins"])
    await interaction.response.send_message(f"🎰 結果: {res} をゲット！\n💰 残金: {p['coins']}コイン", ephemeral=True)
        
@bot.tree.command(name="steal", description="泥棒")
async def steal(interaction: discord.Interaction, target: discord.Member):
    if not await check_channel(interaction, "GACHA"): return
    p, t = get_user_profile(interaction.user.id), get_user_profile(target.id)
    if p["tickets"] < 1: return await interaction.response.send_message("❌ チケット不足", ephemeral=True)
    p["tickets"] -= 1
    stolen = random.randint(50, 200)
    t["coins"] -= stolen; p["coins"] += stolen
    save_data()
    await update_nickname(interaction.user, p["coins"])
    await update_nickname(target, t["coins"])
    await interaction.response.send_message(f"🦹 {stolen}コイン奪った", ephemeral=True)

@bot.tree.command(name="chinchiro_start", description="対人戦チンチロ開始")
async def chinchiro_start(interaction: discord.Interaction):
    if not await check_channel(interaction, "GAMBLE"): return
    cid = interaction.channel.id
    if cid not in chinchiro_rooms or len(chinchiro_rooms[cid]) < 2:
        return await interaction.response.send_message("❌ 2人以上の参加が必要です", ephemeral=True)

    p1, p2 = chinchiro_rooms[cid][0], chinchiro_rooms[cid][1]
    await interaction.response.send_message(f"⚔️ {p1['user'].name} vs {p2['user'].name} の勝負開始！")

    async def roll_dice():
        msg = await interaction.followup.send("🎲 サイコロを振っています...")
        dices = []
        for _ in range(3):
            await asyncio.sleep(0.8)
            dices.append(random.randint(1, 6))
            await msg.edit(content=f"🎲 現在の出目: {dices}")
        return sorted(dices, reverse=True)

    res = {}
    for player in [p1, p2]:
        await interaction.followup.send(f"👤 {player['user'].name} の番です！")
        dices = await roll_dice()
        
        # 役の判定ロジック
        if sorted(dices) == [1, 2, 3]:
            score = 0
            role = "ヒフミ (最弱!)"
        elif len(set(dices)) == 1:
            score = dices[0] * 100 # アラシは最強
            role = "アラシ!"
        elif len(set(dices)) == 3:
            score = -1 # 目なし（最弱）
            role = "目なし..."
        else:
            # 2つ同じ目がある場合、残りの目がスコア
            score = sum(dices) - (sum(dices) - (sum(dices) - sum(set(dices)))) # 簡易合計
            # 実際には重複してない数字を出す処理が必要ですが、シンプルに合計値で勝負にします
            score = sum(dices) 
            role = f"{score}の目"

        await interaction.followup.send(f"🎲 {player['user'].name} は {role}！")
        res[player['user'].id] = {"score": score, "bet": player['bet'], "name": player['user'].name}

    # 勝敗判定
    winner_id = max(res, key=lambda x: res[x]["score"])
    loser_id = min(res, key=lambda x: res[x]["score"])
    
    # 引き分け対応
    if res[winner_id]["score"] == res[loser_id]["score"]:
        await interaction.followup.send("🤝 引き分けです！賭け金は戻ります。")
    else:
        pot = res[winner_id]["bet"]
        winner_p = get_user_profile(winner_id)
        loser_p = get_user_profile(loser_id)
        winner_p["coins"] += pot
        loser_p["coins"] -= pot
        save_data()
        await interaction.followup.send(f"🏆 勝者: {res[winner_id]['name']}！ {pot}コイン獲得！\n💰 残金: {winner_p['coins']}コイン")
    
    chinchiro_rooms[cid] = []

@bot.tree.command(name="race_bet", description="競馬")
async def race_bet(interaction: discord.Interaction, horse_num: int, bet: int):
    if not await check_channel(interaction, "GAMBLE"): return
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
    if not await check_channel(interaction, "GAMBLE"): return
    cid = interaction.channel.id
    if not race_bets.get(cid): return await interaction.response.send_message("❌ 誰も賭けていません", ephemeral=True)
    
    total_pool = sum(b['bet'] for b in race_bets[cid].values())
    horse_bets = {i: 0 for i in range(1, 7)}
    for b in race_bets[cid].values(): horse_bets[b['horse']] += b['bet']
    
    odds_text = "\n".join([f"{horses[h]}: {max(1.1, round(total_pool/pool, 1)) if pool>0 else '---'}倍" for h, pool in horse_bets.items()])
    
    await interaction.response.send_message(f"🟢 レース開始！\n【オッズ】\n{odds_text}")
    msg = await interaction.followup.send("🏁 実況: レースが始まりました！")
    
    progress = {i: 0 for i in range(1, 7)}
    for _ in range(15):
        await asyncio.sleep(1.0)
        for h in progress: progress[h] += random.randint(0, 3)
        await msg.edit(content=f"🏁 実況中...\n" + "\n".join([f"{horses[h]}: {'・'*progress[h]}🏇" for h in progress]))
    
    winner = max(progress, key=progress.get)
    await interaction.followup.send(f"👑 優勝は {horses[winner]}！")
    
    # 結果発表と所持金の表示
    for u_id, b in race_bets[cid].items():
        p = get_user_profile(u_id)
        if b["horse"] == winner: 
            payout = int(b["bet"] * max(1.1, (total_pool / horse_bets[winner])))
            p["coins"] += payout
            status_text = f"🎉 的中！ {payout}コイン獲得！"
        else:
            status_text = "残念...不的中です。"
        
        m = interaction.guild.get_member(u_id)
        if m: 
            await update_nickname(m, p["coins"])
            # 個別に結果と残金を通知
            await interaction.followup.send(f"👤 <@{u_id}>: {status_text}\n💰 現在の所持金: {p['coins']}コイン")
            
    race_bets[cid] = {}; save_data()
@bot.tree.command(name="odds", description="現在のオッズを確認")
async def odds(interaction: discord.Interaction):
    if not await check_channel(interaction, "GAMBLE"): return
    
    cid = interaction.channel.id
    if cid not in race_bets or not race_bets[cid]:
        return await interaction.response.send_message("❌ まだ誰も賭けていません。", ephemeral=True)
    
    total_pool = sum(b['bet'] for b in race_bets[cid].values())
    horse_bets = {i: 0 for i in range(1, 7)}
    for b in race_bets[cid].values(): horse_bets[b['horse']] += b['bet']
    
    odds_text = "\n".join([f"{horses[h]}: {max(1.1, round(total_pool/pool, 1)) if pool>0 else '---'}倍" for h, pool in horse_bets.items()])
    
    await interaction.response.send_message(f"📊 **現在のオッズ**\n{odds_text}")
@bot.tree.command(name="trade", description="他人にアイテムを売る/あげる")
@app_commands.describe(member="相手", item_type="アイテム", price="価格(0で無料)")
@app_commands.choices(item_type=[
    app_commands.Choice(name="お守り", value="shields"),
    app_commands.Choice(name="泥棒チケット", value="tickets")
])
async def trade(interaction: discord.Interaction, member: discord.Member, item_type: str, price: int):
    if not await check_channel(interaction, "GACHA"): return
    
    sender = get_user_profile(interaction.user.id)
    receiver = get_user_profile(member.id)
    
    # 所持チェック
    if sender[item_type] <= 0:
        return await interaction.response.send_message("❌ そのアイテムを持っていません。", ephemeral=True)
    
    # 相手のコインチェック（価格設定がある場合）
    if price > 0 and receiver["coins"] < price:
        return await interaction.response.send_message(f"❌ 相手の所持金が足りません。", ephemeral=True)
    
    # 取引実行
    sender[item_type] -= 1
    receiver[item_type] += 1
    
    if price > 0:
        sender["coins"] += price
        receiver["coins"] -= price
        await update_nickname(member, receiver["coins"])
        result_msg = f"{member.mention} にアイテムを {price}コイン で売却しました！"
    else:
        result_msg = f"{member.mention} にアイテムを譲渡しました！"
        
    save_data()
    await update_nickname(interaction.user, sender["coins"])
    
    await interaction.response.send_message(result_msg, ephemeral=True)

bot.run(os.getenv("DISCORD_TOKEN"))