import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
import asyncio
import os
import time
from flask import Flask
import threading
from supabase import create_client, Client

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

CHANNELS = {"GACHA": "ガチャ", "GAMBLE": "賭け場", "STATUS": "ステータス", "LOG": "通話履歴", "BACKUP": "データ保存"}
race_bets = {}
call_start_times = {}
horses = {1: "🐴ドロボウキング", 2: "🐴オマモリマル", 3: "🐴チンチロマスター", 4: "🐴コゼニデント"}

# --- 💾 Supabase 接続設定 ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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

def get_user_profile(user_id: int) -> dict:
    """Supabaseからユーザーデータを取得。存在しない場合は新規作成"""
    try:
        response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
        if response.data:
            return response.data[0]
        
        # データがない場合は新規登録（初期値: コイン1000枚）
        new_profile = {"user_id": user_id, "coins": 1000, "shields": 0, "tickets": 0}
        supabase.table("user_profiles").insert(new_profile).execute()
        return new_profile
    except Exception as e:
        print(f"データ取得エラー: {e}")
        return {"user_id": user_id, "coins": 0, "shields": 0, "tickets": 0}

def save_supabase_data(user_id: int, data: dict):
    """特定のユーザーのデータをSupabaseに即時保存する"""
    try:
        # 保存用にデータを整形（user_idを固定）
        save_data = {
            "user_id": user_id,
            "coins": data.get("coins", 1000),
            "shields": data.get("shields", 0),
            "tickets": data.get("tickets", 0)
        }
        supabase.table("user_profiles").update(save_data).eq("user_id", user_id).execute()
    except Exception as e:
        print(f"データ保存エラー: {e}")

# --- 🎤 通話報酬 ---
@tasks.loop(minutes=1.0)
async def income_timer():
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if not member.bot:
                    p = get_user_profile(member.id)
                    p["coins"] += 10
                    save_supabase_data(member.id, p)  # Supabaseに保存
                    await update_nickname(member, p["coins"])

@bot.event
async def on_ready():
    await bot.tree.sync()
    income_timer.start()
    
    # 起動時に通話中のメンバーを検知
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
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
    
    if roll <= 50:
        if random.randint(1, 100) <= 2:
            win = random.randint(2300, 2500)
            res = f"💎✨ 超超超大当たり！ {win}コイン"
        else:
            win = random.randint(50, 400)
            res = f"🎉 {win}コイン"
        p["coins"] += win
        
    elif roll <= 85:
        res = "💨 ハズレ"
    else:
        item_type = random.choice(["お守り", "泥棒チケット"])
        if item_type == "お守り":
            p["shields"] += 1
            res = "🛡️ お守り"
        else:
            p["tickets"] += 1
            res = "🎫 泥棒チケット"
        
    save_supabase_data(interaction.user.id, p)  # Supabaseに保存
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
    
    save_supabase_data(interaction.user.id, p)  # 自分のデータを保存
    save_supabase_data(target.id, t)            # 相手のデータを保存
    
    await update_nickname(interaction.user, p["coins"])
    await update_nickname(target, t["coins"])
    await interaction.response.send_message(f"🦹 {stolen}コイン奪った", ephemeral=True)

chinchiro_rooms = {}

@bot.tree.command(name="chinchiro_join", description="チンチロに参加")
async def chinchiro_join(interaction: discord.Interaction, bet: int):
    if not await check_channel(interaction, "GAMBLE"): return
    cid = interaction.channel.id
    if cid not in chinchiro_rooms: chinchiro_rooms[cid] = []
    
    # 既に参加しているか確認
    if any(p['user'].id == interaction.user.id for p in chinchiro_rooms[cid]):
        return await interaction.response.send_message("❌ 既に参加しています", ephemeral=True)
        
    p = get_user_profile(interaction.user.id)
    if p["coins"] < bet: return await interaction.response.send_message("❌ コインが足りません", ephemeral=True)
    
    chinchiro_rooms[cid].append({"user": interaction.user, "bet": bet})
    await interaction.response.send_message(f"🎲 {interaction.user.name} が {bet} コインでチンチロに参加しました！")

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
        
        if sorted(dices) == [1, 2, 3]:
            score = 0
            role = "ヒフミ (最弱!)"
        elif len(set(dices)) == 1:
            score = dices[0] * 100
            role = "アラシ!"
        elif len(set(dices)) == 3:
            score = -1
            role = "目なし..."
        else:
            score = sum(dices) 
            role = f"{score}の目"

        await interaction.followup.send(f"🎲 {player['user'].name} は {role}！")
        res[player['user'].id] = {"score": score, "bet": player['bet'], "name": player['user'].name}

    winner_id = max(res, key=lambda x: res[x]["score"])
    loser_id = min(res, key=lambda x: res[x]["score"])
    
    if res[winner_id]["score"] == res[loser_id]["score"]:
        await interaction.followup.send("🤝 引き分けです！賭け金は戻ります。")
    else:
        pot = res[winner_id]["bet"]
        winner_p = get_user_profile(winner_id)
        loser_p = get_user_profile(loser_id)
        winner_p["coins"] += pot
        loser_p["coins"] -= pot
        
        save_supabase_data(winner_id, winner_p)  # 勝者のデータを保存
        save_supabase_data(loser_id, loser_p)    # 敗者のデータを保存
        
        await interaction.followup.send(f"🏆 勝者: {res[winner_id]['name']}！ {pot}コイン獲得！\n💰 残金: {winner_p['coins']}コイン")
    
    chinchiro_rooms[cid] = []

@bot.tree.command(name="race_bet", description="競馬")
async def race_bet(interaction: discord.Interaction, horse_num: int, bet: int):
    if not await check_channel(interaction, "GAMBLE"): return
    cid = interaction.channel.id
    if cid not in race_bets: race_bets[cid] = {}
    p = get_user_profile(interaction.user.id)
    if p["coins"] < bet: return await interaction.response.send_message("❌ 不足", ephemeral=True)
    
    p["coins"] -= bet
    race_bets[cid][interaction.user.id] = {"horse": horse_num, "bet": bet}
    
    save_supabase_data(interaction.user.id, p)  # 掛け金を引いた状態で保存
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
    
    for u_id, b in race_bets[cid].items():
        p = get_user_profile(u_id)
        if b["horse"] == winner: 
            payout = int(b["bet"] * max(1.1, (total_pool / horse_bets[winner])))
            p["coins"] += payout
            status_text = f"🎉 的中！ {payout}コイン獲得！"
        else:
            status_text = "残念...不定期です。"
        
        save_supabase_data(u_id, p)  # レース結果をSupabaseに保存
        
        m = interaction.guild.get_member(u_id)
        if m: 
            await update_nickname(m, p["coins"])
            await interaction.followup.send(f"👤 <@{u_id}>: {status_text}\n💰 現在の所持金: {p['coins']}コイン")
            
    race_bets[cid] = {}

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
    
    if sender[item_type] <= 0:
        return await interaction.response.send_message("❌ そのアイテムを持っていません。", ephemeral=True)
    
    if price > 0 and receiver["coins"] < price:
        return await interaction.response.send_message(f"❌ 相手の所持金が足りません。", ephemeral=True)
    
    sender[item_type] -= 1
    receiver[item_type] += 1
    
    if price > 0:
        sender["coins"] += price
        receiver["coins"] -= price
        await update_nickname(member, receiver["coins"])
        result_msg = f"{member.mention} にアイテムを {price}コイン で売却しました！"
    else:
        result_msg = f"{member.mention} にアイテムを譲渡しました！"
        
    save_supabase_data(interaction.user.id, sender)  # 送り側のデータを保存
    save_supabase_data(member.id, receiver)          # 受け取り側のデータを保存
    await update_nickname(interaction.user, sender["coins"])
    
    await interaction.response.send_message(result_msg, ephemeral=True)

@bot.tree.command(name="compensation", description="【管理者用】ユーザーにコインを補填する")
@app_commands.describe(member="補填する相手", coins="付与するコイン数")
async def compensation(interaction: discord.Interaction, member: discord.Member, coins: int):
    if interaction.channel.name != "運営さんの部屋":
        return await interaction.response.send_message("❌ このチャンネルでは補填コマンドは使用できません。", ephemeral=True)
        
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ あなたにはこのコマンドを実行する権限がありません。", ephemeral=True)

    p = get_user_profile(member.id)
    p["coins"] += coins
    
    save_supabase_data(member.id, p)  # 補填データを保存
    await update_nickname(member, p["coins"])
    
    await interaction.response.send_message(
        f"📢 【補填完了】\n"
        f"{member.mention} に {coins} コインを補填しました。\n"
        f"💰 相手の現在の所持金: {p['coins']} コイン"
    )
@bot.tree.command(name="backup", description="【管理者用】現在のデータベースのバックアップをチャンネルに出力します")
async def backup(interaction: discord.Interaction):
    # チャンネルチェック
    if not await check_channel(interaction, "BACKUP"): return
    
    # 管理者権限チェック
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ あなたにはこのコマンドを実行する権限がありません。", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True) # 処理に時間がかかる場合があるので待たせる
    
    try:
        # Supabaseからすべてのユーザーデータを取得
        response = supabase.table("user_profiles").select("*").execute()
        data = response.data
        
        if not data:
            return await interaction.followup.send("📁 データベースは空っぽです。", ephemeral=True)
            
        # 読みやすいテキストに整形
        backup_text = f"📦 **【Supabase データベースデータ・バックアップ】**\n取得日時: <t:{int(time.time())}:F>\n------------------------------\n"
        for row in data:
            backup_text += (
                f"👤 ユーザーID: `{row['user_id']}`\n"
                f"  💰 コイン: {row['coins']} | 🛡️ お守り: {row['shields']} | 🎫 チケット: {row['tickets']}\n"
                f"------------------------------\n"
            )
            
        # 文字数制限（2000文字）対策。もしデータが長すぎたら分割して送る
        if len(backup_text) > 1900:
            # データが多すぎる場合は設定ファイル（JSON）風にしてファイルとして送信
            import io
            import json
            file_data = json.dumps(data, ensure_ascii=False, indent=4)
            file = discord.File(fp=io.StringIO(file_data), filename=f"backup_{int(time.time())}.json")
            await interaction.channel.send(content=f"📦 **【Supabase バックアップファイル】**\n取得日時: <t:{int(time.time())}:F>", file=file)
        else:
            # 文字数に収まるならそのままメッセージとして投稿
            await interaction.channel.send(backup_text)
            
        await interaction.followup.send("✅ バックアップをチャンネルに出力しました！", ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"❌ バックアップ作成中にエラーが発生しました: {e}", ephemeral=True)

bot.run(os.getenv("DISCORD_TOKEN"))