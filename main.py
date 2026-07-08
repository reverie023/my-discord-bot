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

# バックアップ用チャンネルを追加したチャンネルリスト
CHANNELS = {"GACHA": "ガチャ", "GAMBLE": "賭け場", "STATUS": "ステータス", "LOG": "通話履歴", "BACKUP": "データ保存", "SLOT":"スロットマシーン"}
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
    """Supabaseからユーザーデータを取得。存在しない場合は新規作成して保存"""
    try:
        response = supabase.table("user_profiles").select("*").eq("user_id", user_id).execute()
        if response.data:
            return response.data[0]
        
        # データがない場合は初期値を用意して速やかにupsert（新規登録）
        new_profile = {"user_id": user_id, "coins": 1000, "shields": 0, "tickets": 0}
        supabase.table("user_profiles").upsert(new_profile).execute()
        return new_profile
    except Exception as e:
        print(f"データ取得エラー: {e}")
        return {"user_id": user_id, "coins": 1000, "shields": 0, "tickets": 0}

def save_supabase_data(user_id: int, data: dict):
    """特定のユーザーのデータをSupabaseに即時保存する（存在しなければ新規作成、あれば更新）"""
    try:
        save_data = {
            "user_id": user_id,
            "coins": int(data.get("coins", 1000)),
            "shields": int(data.get("shields", 0)),
            "tickets": int(data.get("tickets", 0))
        }
        # updateからupsertに変更し、空のデータベースでのエラーを完全に回避
        supabase.table("user_profiles").upsert(save_data).execute()
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
                    save_supabase_data(member.id, p)
                    await update_nickname(member, p["coins"])

@bot.event
async def on_ready():
    await bot.tree.sync()
    income_timer.start()
    
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
        
    save_supabase_data(interaction.user.id, p)
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
    
    save_supabase_data(interaction.user.id, p)
    save_supabase_data(target.id, t)
    await update_nickname(interaction.user, p["coins"])
    await update_nickname(target, t["coins"])
    await interaction.response.send_message(f"🦹 {stolen}コイン奪った", ephemeral=True)

chinchiro_rooms = {}

@bot.tree.command(name="chinchiro_start", description="対人戦チンチロ開始")
async def chinchiro_start(interaction: discord.Interaction):
    if not await check_channel(interaction, "GAMBLE"): return
    cid = interaction.channel.id
    if cid not in chinchiro_rooms or len(chinchiro_rooms[cid]) < 2:
        return await interaction.response.send_message("❌ 2人以上の参加が必要です", ephemeral=True)

    p1, p2 = chinchiro_rooms[cid][0], chinchiro_rooms[cid][1]
    dice_emojis = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
    
    await interaction.response.send_message(f"⚔️ **【チンチロ勝負開始】** ⚔️\n🔥 **{p1['user'].name}** (賭け金: {p1['bet']})  vs  🔥 **{p2['user'].name}** (賭け金: {p2['bet']})")

    # 🎲 サイコロを1回振る内部関数
    async def roll_dice():
        msg = await interaction.followup.send("🎲 *ザワ…ザワ… サイコロを振っています…*")
        dices = []
        for _ in range(3):
            await asyncio.sleep(0.6)
            dices.append(random.randint(1, 6))
            current_emojis = " ".join([dice_emojis[d] for d in dices])
            await msg.edit(content=f"🎲 振られたサイコロ:  **{current_emojis}**")
        return sorted(dices, reverse=True)

    res = {}
    for player in [p1, p2]:
        await interaction.followup.send(f"\n━━━━━━━━━━━━━━━━━━━━━\n👤 **{player['user'].name}** のターン！")
        
        # 🔄 最大3回振るループ処理
        for attempt in range(1, 4):
            if attempt > 1:
                await interaction.followup.send(f"🔄 **{attempt}回目の振り直しです！**")
                
            dices = await roll_dice()
            final_emojis = " ".join([dice_emojis[d] for d in dices])
            
            # 役の判定
            if sorted(dices) == [1, 2, 3]:
                score = -999  # 絶対に負けるように最弱のスコアを設定
                role = "💀❌ **ヒフミ (一発即死負け!!!)**"
                is_reroll_target = False  # 振り直さずに即確定！
            elif len(set(dices)) == 1:
                score = dices[0] * 100
                role = f"✨👑 **アラシ ({dices[0]}のゾロ目)!!**"
                is_reroll_target = False
            elif len(set(dices)) == 3:
                score = -1
                role = "💨 **目なし...**"
                is_reroll_target = True  # 目なしは振り直しOK！
            else:
                if dices[0] == dices[1]:
                    score = dices[2]
                else:
                    score = dices[0]
                role = f"🎯 **【 {score} の目 】**"
                is_reroll_target = False

            await interaction.followup.send(f"🎲 {attempt}回目出目: {final_emojis} ➡️ 結果: {role}")
            
            # 振り直し対象（目なし）でなければ、ループを抜けて結果を確定
            if not is_reroll_target:
                break
            
            # 3回目も目なしだった場合
            if attempt == 3:
                await interaction.followup.send(f"💥 3回すべて【目なし】のため、これで記録確定です！")

        res[player['user'].id] = {"score": score, "bet": player['bet'], "name": player['user'].name}

    await asyncio.sleep(1.0)
    await interaction.followup.send("\n👑━━━━━━━━━━━━━━━━━━━━━👑\n📊 **【 最終結果発表 】**")

    winner_id = max(res, key=lambda x: res[x]["score"])
    loser_id = min(res, key=lambda x: res[x]["score"])
    
    if res[winner_id]["score"] == res[loser_id]["score"]:
        await interaction.followup.send("🤝 **引き分け！** 賭け金は全員に戻されます。")
    else:
        pot = res[winner_id]["bet"]
        winner_p = get_user_profile(winner_id)
        loser_p = get_user_profile(loser_id)
        winner_p["coins"] += pot
        loser_p["coins"] -= pot
        
        save_supabase_data(winner_id, winner_p)
        save_supabase_data(loser_id, loser_p)
        
        await interaction.followup.send(
            f"🏆 **勝者:** {res[winner_id]['name']} 🌟\n"
            f"💰 **獲得コイン:** `+{pot}` コイン\n"
            f"📈 **現在の所持金:** {winner_p['coins']} コイン"
        )
    
    chinchiro_rooms[cid] = []

@bot.tree.command(name="chinchiro_solo", description="コンピューターと対戦するソロチンチロ（自分だけに通知）")
@app_commands.describe(bet="賭けるコインの数")
async def chinchiro_solo(interaction: discord.Interaction, bet: int):
    if not await check_channel(interaction, "GAMBLE"): return
    if bet <= 0:
        return await interaction.response.send_message("❌ 1コイン以上を賭けてください", ephemeral=True)

    uid = interaction.user.id
    profile = get_user_profile(uid)
    
    if profile["coins"] < bet:
        return await interaction.response.send_message(f"❌ コインが足りません（所持: {profile['coins']} コイン）", ephemeral=True)

    # コインを引く
    profile["coins"] -= bet
    save_supabase_data(uid, profile)

    dice_emojis = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
    
    await interaction.response.send_message(
        f"⚔️ **【ソロチンチロ勝負開始】** ⚔️\n"
        f"👤 **{interaction.user.name}** vs 🤖 **コンピューター**\n"
        f"💰 賭け金: `{bet}` コイン", 
        ephemeral=True
    )

    # 🎲 サイコロを振る内部関数
    async def roll_dice(player_name):
        msg = await interaction.followup.send(f"🎲 *{player_name} がサイコロを振っています…*", ephemeral=True)
        dices = []
        for _ in range(3):
            await asyncio.sleep(0.5)
            dices.append(random.randint(1, 6))
            current_emojis = " ".join([dice_emojis[d] for d in dices])
            await msg.edit(content=f"🎲 {player_name} のサイコロ:  **{current_emojis}**")
        return sorted(dices, reverse=True)

    # 🔄 ターンを処理する関数（目なしなら最大3回）
    async def play_turn(player_name):
        score = -1
        role = "💨 目なし"
        
        for attempt in range(1, 4):
            if attempt > 1:
                await interaction.followup.send(f"🔄 🤖 *コンピューターが空気を読んで {attempt}回目の振り直し中…*" if player_name == "🤖" else f"🔄 **{attempt}回目の振り直しです！**", ephemeral=True)
                
            dices = await roll_dice(player_name)
            final_emojis = " ".join([dice_emojis[d] for d in dices])
            
            # 役判定
            if sorted(dices) == [1, 2, 3]:
                score = -999
                role = "💀❌ **ヒフミ (一発即死負け!!!)**"
                is_reroll = False
            elif len(set(dices)) == 1:
                score = dices[0] * 100
                role = f"✨👑 **アラシ ({dices[0]}のゾロ目)!!**"
                is_reroll = False
            elif len(set(dices)) == 3:
                score = -1
                role = "💨 **目なし...**"
                is_reroll = True
            else:
                score = dices[2] if dices[0] == dices[1] else dices[0]
                role = f"🎯 **【 {score} の目 】**"
                is_reroll = False

            await interaction.followup.send(f"🎲 {player_name} ({attempt}回目): {final_emojis} ➡️ 結果: {role}", ephemeral=True)
            
            if not is_reroll:
                break
            if attempt == 3:
                await interaction.followup.send(f"💥 {player_name} は3回すべて【目なし】で確定！", ephemeral=True)
                
        return score, role

    # 1. プレイヤーのターン
    await interaction.followup.send(f"\n━━━━━━━━━━━━━━━━━━━━━\n👤 **あなたのターン！**", ephemeral=True)
    p_score, p_role = await play_turn(interaction.user.name)

    # 2. コンピューターのターン
    await asyncio.sleep(1.0)
    await interaction.followup.send(f"\n━━━━━━━━━━━━━━━━━━━━━\n🤖 **コンピューターのターン！**", ephemeral=True)
    c_score, c_role = await play_turn("🤖")

    # 3. 結果発表
    await asyncio.sleep(1.0)
    await interaction.followup.send("\n👑━━━━━━━━━━━━━━━━━━━━━👑\n📊 **【 最終結果発表 】**", ephemeral=True)

    if p_score == c_score:
        profile["coins"] += bet  # コインを戻す
        save_supabase_data(uid, profile)
        await interaction.followup.send(f"🤝 **引き分け！** 賭け金 `{bet}` コインが戻されました。\n💰 所持金: {profile['coins']} コイン", ephemeral=True)
    elif p_score > c_score:
        payout = bet * 2
        profile["coins"] += payout
        save_supabase_data(uid, profile)
        await update_nickname(interaction.user, profile["coins"])
        await interaction.followup.send(
            f"🏆 **あなたの勝ち！** 🌟\n"
            f"💰 **獲得コイン:** `+{bet}` コイン（倍返し！）\n"
            f"📈 **現在の所持金:** {profile['coins']} コイン",
            ephemeral=True
        )
    else:
        await update_nickname(interaction.user, profile["coins"])
        await interaction.followup.send(
            f"💀 **あなたの負け！** コンピューターの勝利です。\n"
            f"💸 賭け金 `{bet}` コインを失いました…。\n"
            f"📉 **現在の所持金:** {profile['coins']} コイン",
            ephemeral=True
        )

# --- 🏇 競馬システム ---
@bot.tree.command(name="race_bet", description="競馬にベットします")
@app_commands.describe(horse_num="賭ける馬の番号 (1〜4)", bet="賭けるコインの数")
async def race_bet(interaction: discord.Interaction, horse_num: int, bet: int):
    if not await check_channel(interaction, "GAMBLE"): return
    if horse_num not in horses:
        return await interaction.response.send_message("❌ 存在しない馬の番号です。1〜4の中から選んでください。", ephemeral=True)
    if bet <= 0:
        return await interaction.response.send_message("❌ 1コイン以上を賭けてください。", ephemeral=True)

    cid = interaction.channel.id
    if cid not in race_bets: race_bets[cid] = {}
    
    p = get_user_profile(interaction.user.id)
    if p["coins"] < bet: 
        return await interaction.response.send_message(f"❌ コインが足りません。現在の所持金: {p['coins']}コイン", ephemeral=True)
    
    p["coins"] -= bet
    race_bets[cid][interaction.user.id] = {"horse": horse_num, "bet": bet}
    
    save_supabase_data(interaction.user.id, p)
    await update_nickname(interaction.user, p["coins"])
    await interaction.response.send_message(f"🏁 **{horses[horse_num]}** に {bet}コイン 賭けました！ (残金: {p['coins']})", ephemeral=True)

@bot.tree.command(name="race_start", description="レースを開始します")
async def race_start(interaction: discord.Interaction):
    if not await check_channel(interaction, "GAMBLE"): return
    cid = interaction.channel.id
    if not race_bets.get(cid): 
        return await interaction.response.send_message("❌ まだ誰も賭けていないため、レースを開始できません。", ephemeral=True)
    
    # --- 🎲 馬ごとにちがうNPC金額（乱数）を個別に生成！ ---
    # 毎レースごとに、1番馬〜4番馬それぞれにまったく別の金額（100〜400）がランダムに割り振られます
    npc_bets = {
        1: random.randint(100, 400),
        2: random.randint(100, 400),
        3: random.randint(100, 400),
        4: random.randint(100, 400)
    }
    
    # 総プール金の計算（プレイヤー全員の賭け金 ＋ 馬ごとに違うNPCの金額の合計）
    total_pool = sum(b['bet'] for b in race_bets[cid].values()) + sum(npc_bets.values())
    
    # 各馬の最終賭け金を集計
    horse_bets = {i: npc_bets[i] for i in horses.keys()}
    for b in race_bets[cid].values(): 
        horse_bets[b['horse']] += b['bet']
    
    # 最終確定オッズの計算
    odds_text = "\n".join([f"{horses[h]}: {max(1.1, round(total_pool/pool, 1))}倍" for h, pool in horse_bets.items()])
    
    await interaction.response.send_message(f"🟢 **ゲートオープン！ レースが開始されました！**\n【確定オッズ（馬別NPC投票含む）】\n{odds_text}")
    msg = await interaction.followup.send("🏁 実況: 各馬一斉にスタートしました！")
    
    progress = {i: 0 for i in horses.keys()}
    for _ in range(15):
        await asyncio.sleep(1.0)
        for h in progress: progress[h] += random.randint(0, 3)
        await msg.edit(content=f"🏁 **実況: 各馬中盤の直線コース！**\n" + "\n".join([f"{horses[h]}: {'・'*progress[h]}🏇" for h in progress]))
    
    winner = max(progress, key=progress.get)
    await interaction.followup.send(f"👑 **見事1着でゴールインしたのは {horses[winner]} ！！！**")
    
    for u_id, b in race_bets[cid].items():
        p = get_user_profile(u_id)
        if b["horse"] == winner: 
            payout = int(b["bet"] * max(1.1, (total_pool / horse_bets[winner])))
            p["coins"] += payout
            status_text = f"🎉 お見事！予想的中です！ **+{payout}** コイン獲得！"
        else:
            status_text = f"❌ 残念...ハズレました。"
        
        save_supabase_data(u_id, p)
        
        m = interaction.guild.get_member(u_id)
        if m: 
            await update_nickname(m, p["coins"])
            await interaction.followup.send(f"👤 <@{u_id}> さん: {status_text}\n💰 現在の所持金: {p['coins']}コイン")
            
    race_bets[cid] = {}

@bot.tree.command(name="odds", description="現在のオッズを確認")
async def odds(interaction: discord.Interaction):
    if not await check_channel(interaction, "GAMBLE"): return
    cid = interaction.channel.id
    
    # --- 🎲 誰も賭けていない場合 ---
    if cid not in race_bets or not race_bets[cid]:
        # 馬ごとにバラバラの乱数（100〜400コイン）をその場で生成してオッズを計算します
        dummy_bets = {i: random.randint(100, 400) for i in horses.keys()}
        total_pool = sum(dummy_bets.values())
        odds_text = "\n".join([f"{horses[h]}: {max(1.1, round(total_pool/pool, 1))}倍" for h, pool in dummy_bets.items()])
        return await interaction.response.send_message(f"📊 **現在の予想オッズ（まだ誰も賭けていません）**\n{odds_text}\n※確認するたびにNPCの投票状況が変わります！")
    
    # --- 🎲 誰かがすでに賭けている場合 ---
    # こちらも馬ごとにバラバラの仮NPC投票（100〜400の乱数）をその場で発生させてプレイヤーの賭け金と合算します
    dummy_bases = {i: random.randint(100, 400) for i in horses.keys()}
    total_pool = sum(b['bet'] for b in race_bets[cid].values()) + sum(dummy_bases.values())
    
    horse_bets = {i: dummy_bases[i] for i in horses.keys()}
    for b in race_bets[cid].values(): 
        horse_bets[b['horse']] += b['bet']
    
    odds_text = "\n".join([f"{horses[h]}: {max(1.1, round(total_pool/pool, 1))}倍" for h, pool in horse_bets.items()])
    await interaction.response.send_message(f"📊 **現在の予想オッズ（馬別NPC仮投票含む）**\n{odds_text}\n※レース開始時（/race_start）にNPCの再投票が行われるため、さらにオッズが変動します！")
    
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
        
    save_supabase_data(interaction.user.id, sender)
    save_supabase_data(member.id, receiver)
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
    
    save_supabase_data(member.id, p)
    await update_nickname(member, p["coins"])
    await interaction.response.send_message(
        f"📢 【補填完了】\n{member.mention} に {coins} コインを補填しました。\n💰 相手の現在の所持金: {p['coins']} コイン"
    )

@bot.tree.command(name="slot", description="スロットマシンを回す（自分だけに通知・ペカり演出あり！）")
async def slot(interaction: discord.Interaction, bet: int):
    if not await check_channel(interaction, "SLOT"): return 
    if bet <= 0:
        return await interaction.response.send_message("❌ 1コイン以上を賭けてください", ephemeral=True)

    uid = interaction.user.id
    profile = get_user_profile(uid)
    
    if profile["coins"] < bet:
        return await interaction.response.send_message(f"❌ コインが足りません（所持: {profile['coins']} コイン）", ephemeral=True)

    # コインを引く
    profile["coins"] -= bet
    save_supabase_data(uid, profile)

    # スロットの絵文字
    emojis = ["🍒", "🔔", "🍉", "🍇", "⭐", "🎰", "💎"]
    
    # 確率の設定（裏で先に結果を決定）
    is_pika = random.random() < 0.05
    is_win = is_pika or (random.random() < 0.20)

    # 最終的な出目の決定
    if is_win:
        hit_emoji = random.choice(["🎰", "💎"]) if is_pika else random.choice(emojis)
        r1, r2, r3 = hit_emoji, hit_emoji, hit_emoji
    else:
        r1 = random.choice(emojis)
        r2 = random.choice([e for e in emojis if e != r1])
        r3 = random.choice([e for e in emojis if e != r2])

    # 📝 【修正ポイント】ここで ephemeral=True を設定することで、このあとの演出がすべて自分専用になります！
    await interaction.response.send_message(f"🎰 **【SLOT MACHINE】** 💰\n🔥 賭け金: `{bet}` コイン を投入しました！", ephemeral=True)
    
    # 最初は全部回転中（こちらも自分だけに見えるように ephemeral=True）
    msg = await interaction.followup.send(
        "✨ **リール回転中...** ✨\n"
        "━━━━━━━━━━\n"
        "  🎰  |  🎰  |  🎰\n"
        "【 ⏳ 】|【 ⏳ 】|【 ⏳ 】\n"
        "━━━━━━━━━━\n"
        "レバーON！ ズガガガガッ！",
        ephemeral=True
    )

    await asyncio.sleep(0.8)

    # 💡 【先ペカ演出】（ephemeral=True を追加）
    if is_pika:
        await interaction.followup.send("✨✨ーーー ⚡ **ズババババッ！！！** ⚡ ーーー✨✨", ephemeral=True)
        await asyncio.sleep(0.5)
        await interaction.followup.send("🎰✨🚨 **【 GOGO! 】ペカッ！！！** 🚨✨🎰\n（ボケェッ！と鳴り響く告知音！ボーナス確定！）", ephemeral=True)
        await asyncio.sleep(1.0)

    # --- 🎰 リールを左から順番に止める演出 ---
    # 1. 左リール停止
    for _ in range(2):
        await msg.edit(content=f"✨ **リール回転中...** ✨\n━━━━━━━━━━\n  🎰  |  🎰  |  🎰\n【 {random.choice(emojis)} 】|【 ⏳ 】|【 ⏳ 】\n━━━━━━━━━━")
        await asyncio.sleep(0.3)
    await msg.edit(content=f"✨ **左リール停止！** ✨\n━━━━━━━━━━\n  🎰  |  🎰  |  🎰\n【 {r1} 】|【 ⏳ 】|【 ⏳ 】\n━━━━━━━━━━")
    await asyncio.sleep(0.6)

    # 2. 中リール停止
    for _ in range(2):
        await msg.edit(content=f"✨ **リール回転中...** ✨\n━━━━━━━━━━\n  🎰  |  🎰  |  🎰\n【 {r1} 】|【 {random.choice(emojis)} 】|【 ⏳ 】\n━━━━━━━━━━")
        await asyncio.sleep(0.3)
    await msg.edit(content=f"✨ **中リール停止！テンパイ…！？** ✨\n━━━━━━━━━━\n  🎰  |  🎰  |  🎰\n【 {r1} 】|【 {r2} 】|【 ⏳ 】\n━━━━━━━━━━")
    await asyncio.sleep(0.8)

    # 3. 右リール停止（最終結果）
    for _ in range(2):
        await msg.edit(content=f"✨ **右リールが滑る...！** ✨\n━━━━━━━━━━\n  🎰  |  🎰  |  🎰\n【 {r1} 】|【 {r2} 】|【 {random.choice(emojis)} 】\n━━━━━━━━━━")
        await asyncio.sleep(0.3)
    await msg.edit(content=f"✨ **最終リール結果** ✨\n━━━━━━━━━━\n  🎰  |  🎰  |  🎰\n【 {r1} 】|【 {r2} 】|【 {r3} 】\n━━━━━━━━━━")

    # 配当倍率チェック
    payout = 0
    result_text = ""

    if r1 == r2 == r3:
        if r1 == "🎰":
            payout = bet * 15
            result_text = "🎉超特大BIG BONUS!!! 🎰が揃いました！"
        elif r1 == "💎":
            payout = bet * 10
            result_text = "💎💎 REGULAR BONUS!! 💎💎"
        elif r1 == "🍒":
            payout = bet * 5
            result_text = "🍒 チェリー重複ヒット！"
        else:
            payout = bet * 3
            result_text = f"🔔 小役ゲット！【{r1}】揃い！"
    else:
        # 💡 【後ペカ演出】（ephemeral=True を追加）
        if not is_win and random.random() < 0.03:
            await asyncio.sleep(0.5)
            await interaction.followup.send("……ん？ 違和感……。", ephemeral=True)
            await asyncio.sleep(0.8)
            await interaction.followup.send("✨🎰🚨 **【 GOGO! 】ペカッ！！！（後告知）** 🚨✨🎰\nなんと単チェリー（または出目矛盾）から、遅れて光りました！", ephemeral=True)
            payout = bet * 8
            result_text = "😭ハズレからの… ⚡復活大逆転ボーナス！"

    # 結果の反映
    if payout > 0:
        profile["coins"] += payout
        save_supabase_data(uid, profile)
        await interaction.followup.send(
            f"🏆 **【WIN】** {result_text}\n"
            f"💰 **配当:** `+{payout}` コイン\n"
            f"📈 **現在の所持金:** {profile['coins']} コイン",
            ephemeral=True
        )
    else:
        await interaction.followup.send(
            f"💀 **【LOSE】** 残念！揃いませんでした…。\n"
            f"📉 **現在の所持金:** {profile['coins']} コイン",
            ephemeral=True
        )

@bot.tree.command(name="backup", description="【管理者用】現在のデータベースのバックアップをチャンネルに出力します")
async def backup(interaction: discord.Interaction):
    if not await check_channel(interaction, "BACKUP"): return
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ あなたにはこのコマンドを実行する権限がありません。", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        response = supabase.table("user_profiles").select("*").execute()
        data = response.data
        if not data:
            return await interaction.followup.send("📁 データベースは空っぽです。", ephemeral=True)
            
        backup_text = f"📦 **【Supabase データベースデータ・バックアップ】**\n取得日時: <t:{int(time.time())}:F>\n------------------------------\n"
        for row in data:
            backup_text += (
                f"👤 ユーザーID: `{row['user_id']}`\n"
                f"  💰 コイン: {row['coins']} | 🛡️ お守り: {row['shields']} | 🎫 チケット: {row['tickets']}\n"
                f"------------------------------\n"
            )
            
        if len(backup_text) > 1900:
            import io
            import json
            file_data = json.dumps(data, ensure_ascii=False, indent=4)
            file = discord.File(fp=io.StringIO(file_data), filename=f"backup_{int(time.time())}.json")
            await interaction.channel.send(content=f"📦 **【Supabase バックアップファイル】**\n取得日時: <t:{int(time.time())}:F>", file=file)
        else:
            await interaction.channel.send(backup_text)
            
        await interaction.followup.send("✅ バックアップをチャンネルに出力しました！", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ バックアップ作成中にエラーが発生しました: {e}", ephemeral=True)

bot.run(os.getenv("DISCORD_TOKEN"))