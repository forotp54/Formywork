import telebot
from telebot import types
import requests
import sqlite3
import logging
import time
import threading
from config import TELEGRAM_BOT_TOKEN, BOT_USERNAME, OSINT_API_KEY, PAYMENT_BOT_USERNAME, SUPPORT_BOT_USERNAME, VERIFICATION_CHANNEL, CHANNEL_ID, ADMIN_USER_ID

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Database setup
conn = sqlite3.connect('users.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users
             (user_id INTEGER PRIMARY KEY, name TEXT, username TEXT, credits INTEGER DEFAULT 4,
              referrals INTEGER DEFAULT 0, status TEXT DEFAULT 'Guest', first_time INTEGER DEFAULT 1,
              verified INTEGER DEFAULT 0)''')
conn.commit()

def get_user(user_id):
    try:
        c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = c.fetchone()
        if row:
            return dict(zip(['user_id', 'name', 'username', 'credits', 'referrals', 'status', 'first_time', 'verified'], row))
    except sqlite3.Error as e:
        logger.error(f"Database error in get_user: {e}")
    return None

def add_user(user_id, name, username):
    try:
        c.execute("INSERT OR IGNORE INTO users (user_id, name, username, credits, referrals, status, first_time, verified) VALUES (?, ?, ?, 4, 0, 'Guest', 1, 0)",
                  (user_id, name, username))
        conn.commit()
        logger.info(f"Added new user: {user_id}")
    except sqlite3.Error as e:
        logger.error(f"Database error in add_user: {e}")

def update_user(user_id, **kwargs):
    try:
        for key, value in kwargs.items():
            c.execute(f"UPDATE users SET {key}=? WHERE user_id=?", (value, user_id))
        conn.commit()
        logger.info(f"Updated user {user_id}: {kwargs}")
    except sqlite3.Error as e:
        logger.error(f"Database error in update_user: {e}")

def is_user_member(user_id):
    try:
        chat_id = CHANNEL_ID
        logger.info(f"Checking membership for user {user_id} in chat {chat_id}")
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking membership for {user_id} in {chat_id}: {e}")
        return False

def get_main_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    osint_btn = types.InlineKeyboardButton("📦 OSINT", callback_data="osint")
    profile_btn = types.InlineKeyboardButton("👤 Profile", callback_data="profile")
    ref_btn = types.InlineKeyboardButton("🎁 Referral", callback_data="referral")
    purchase_btn = types.InlineKeyboardButton("💳 Purchase", callback_data="purchase")
    support_btn = types.InlineKeyboardButton("📞 Support", url=f"https://t.me/{SUPPORT_BOT_USERNAME}")
    markup.add(osint_btn, profile_btn)
    markup.add(ref_btn, purchase_btn)
    markup.add(support_btn)
    return markup

def show_menu(chat_id):
    markup = get_main_menu()
    bot.send_message(chat_id, "💡 Choose an option:", reply_markup=markup)

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    name = message.from_user.first_name or "Unknown"
    username = message.from_user.username or None
    
    user = get_user(user_id)
    if not user:
        add_user(user_id, name, username)
        user = get_user(user_id)
    
    if not user['verified']:
        if not is_user_member(user_id):
            markup = types.InlineKeyboardMarkup()
            join_btn = types.InlineKeyboardButton("🔗 Join Channel", url=f"https://t.me/{VERIFICATION_CHANNEL.replace('@', '')}")
            check_btn = types.InlineKeyboardButton("✅ Check Membership", callback_data="check_verify")
            markup.add(join_btn, check_btn)
            bot.send_message(message.chat.id, f"🚫 Please join our channel {VERIFICATION_CHANNEL} first to access the bot!", reply_markup=markup)
            return
        else:
            update_user(user_id, verified=1)
            bot.send_message(message.chat.id, "✅ Verified! Welcome aboard! 🚀")
    
    args = message.text.split()
    if len(args) > 1 and args[1].startswith('ref_'):
        try:
            ref_id = int(args[1][4:])
            if ref_id != user_id and get_user(ref_id):
                update_user(ref_id, referrals=get_user(ref_id)['referrals'] + 1, credits=get_user(ref_id)['credits'] + 2)
                bot.send_message(ref_id, "🎉 New referral! +2 credits awarded! 📈")
                logger.info(f"Referral reward given to {ref_id} from {user_id}")
        except ValueError:
            pass
    
    status_emoji = "👑 Premium" if user['status'] == 'Premium' else "👤 Guest"
    text = f"""🔍 Welcome to OSINT BOT 😊

🔎 You can search anything here...

👋 Hey there, {name}!

🆔 User ID: {user_id}
💰 Credits: {user['credits']}
{status_emoji}

💡 Explore the features below! 💡"""
    
    if user['first_time']:
        update_user(user_id, first_time=0)
        bot.send_message(message.chat.id, "🎁 Starter bonus: +4 credits added! Enjoy your searches! ✨")
    
    bot.send_message(message.chat.id, text, reply_markup=get_main_menu(), parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data == "check_verify")
def check_verify(call):
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    if is_user_member(user_id):
        update_user(user_id, verified=1)
        bot.edit_message_text("✅ Membership verified! Starting bot...", call.message.chat.id, call.message.message_id)
        start(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ Still not joined. Please join the channel!", show_alert=True)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    user = get_user(user_id)
    
    # Delete previous message when a button is clicked
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except:
        pass  # Ignore if can't delete
    
    if not user or not user['verified']:
        if not is_user_member(user_id):
            markup = types.InlineKeyboardMarkup()
            join_btn = types.InlineKeyboardButton("🔗 Join Channel", url=f"https://t.me/{VERIFICATION_CHANNEL.replace('@', '')}")
            markup.add(join_btn)
            bot.send_message(chat_id, f"🚫 Join {VERIFICATION_CHANNEL} to continue!", reply_markup=markup)
            return
    
    data = call.data
    if data == "osint":
        bot.send_message(chat_id, "📱 Enter a 10-digit phone number to search:")
        bot.register_next_step_handler(bot.send_message(chat_id, "📱 Enter a 10-digit phone number to search:"), process_phone_number)
    
    elif data == "profile":
        status_emoji = "👑 Premium" if user['status'] == 'Premium' else "👤 Guest"
        username_display = f"@{user['username']}" if user['username'] else "None"
        text = f"""😊 Welcome! Thanks for using OSINT BOT!

👤 User Profile

👤 Name: {user['name']}
🔰 Username: {username_display}
🆔 User ID: {user['user_id']}

💰 Credits: {user['credits']}
🎁 Total Referrals: {user['referrals']}

{status_emoji}"""
        markup = types.InlineKeyboardMarkup()
        back_btn = types.InlineKeyboardButton("🔙 Back", callback_data="back_main")
        markup.add(back_btn)
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
    
    elif data == "referral":
        ref_link = f"https://t.me/{BOT_USERNAME.replace('@', '')}?start=ref_{user_id}"
        text = f"""📢 Share your unique referral link:

🔗 {ref_link}

👥 Invite friends & earn +2 credits per successful referral!
📊 Track progress in Profile."""
        markup = types.InlineKeyboardMarkup()
        back_btn = types.InlineKeyboardButton("🔙 Back", callback_data="back_main")
        markup.add(back_btn)
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
    
    elif data == "purchase":
        markup = types.InlineKeyboardMarkup(row_width=1)
        btn1 = types.InlineKeyboardButton("💰 20₹ = 10 Credits", callback_data="buy_10")
        btn2 = types.InlineKeyboardButton("💎 30₹ = 20 Credits", callback_data="buy_20")
        back_btn = types.InlineKeyboardButton("🔙 Back", callback_data="back_main")
        markup.add(btn1, btn2, back_btn)
        bot.send_message(chat_id, "🛒 Choose a credit package:", reply_markup=markup)
    
    elif data.startswith("buy_"):
        credits = 10 if "10" in data else 20
        price = 20 if credits == 10 else 30
        text = f"""💳 Selected Package:
💰 {price}₹ → {credits} Credits

📝 Steps:
1️⃣ Pay to @{PAYMENT_BOT_USERNAME}
2️⃣ Send proof to @{SUPPORT_BOT_USERNAME}
3️⃣ Credits will be added instantly!

⚠️ No redeem codes needed."""
        markup = types.InlineKeyboardMarkup()
        back_btn = types.InlineKeyboardButton("🔙 Back", callback_data="back_main")
        markup.add(back_btn)
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
    
    elif data == "back_main":
        show_menu(chat_id)

@bot.message_handler(commands=['addcredits'])
def add_credits(message):
    if message.from_user.id != ADMIN_USER_ID:
        bot.reply_to(message, "🚫 Only the main admin can add credits!")
        return
    
    try:
        args = message.text.split()
        if len(args) != 3:
            bot.reply_to(message, "❌ Format: /addcredits <user_id> <credits>")
            return
        
        user_id = int(args[1])
        credits_add = int(args[2])
        
        user = get_user(user_id)
        if not user:
            bot.reply_to(message, "❌ User not found.")
            return
        
        new_credits = user['credits'] + credits_add
        new_status = 'Premium' if new_credits >= 10 else user['status']
        update_user(user_id, credits=new_credits, status=new_status)
        
        bot.reply_to(message, f"✅ Added {credits_add} credits to {user_id}. Total: {new_credits} | Status: {new_status}")
        try:
            bot.send_message(user_id, f"🎉 +{credits_add} credits added! New balance: {new_credits} | Status: {new_status}")
        except:
            pass
    except ValueError:
        bot.reply_to(message, "❌ Invalid numbers.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
        logger.error(f"Add credits error: {e}")

@bot.message_handler(func=lambda message: True)
def handle_unknown(message):
    bot.reply_to(message, "❓ Use /start to begin or select from menu.")

def process_phone_number(message):
    number = message.text.strip()
    chat_id = message.chat.id
    user_id = message.from_user.id
    user = get_user(user_id)
    
    if not user:
        bot.send_message(chat_id, "❌ User not found. Restart with /start.")
        return
    
    if len(number) != 10 or not number.isdigit():
        bot.send_message(chat_id, "❌ Invalid! Use exactly 10 digits (e.g., 9876543210).")
        bot.register_next_step_handler(bot.send_message(chat_id, "📱 Enter 10-digit number:"), process_phone_number)
        return
    
    if user['credits'] < 2:
        bot.send_message(chat_id, "❌ Low credits! Need 2 for search. Buy more via Purchase.")
        show_menu(chat_id)
        return
    
    searching_msg = bot.send_message(chat_id, "🔍 Searching... Please wait ⏳")
    
    new_credits = user['credits'] - 2
    update_user(user_id, credits=new_credits)
    
    url = f"https://api.oblivionhunters.com/details?phone={number}&api_key={OSINT_API_KEY}"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        api_data = response.json()
        
        bot.delete_message(chat_id, searching_msg.message_id)
        
        if api_data.get('status') != 'success':
            bot.send_message(chat_id, "❌ Search failed. Try another number.")
            show_menu(chat_id)
            return
        
        results_count = api_data.get('results_count', 0)
        data_list = api_data.get('data', [])
        
        if results_count == 0:
            bot.send_message(chat_id, "❌ No results found for this number.")
            show_menu(chat_id)
            return
        
        output = "✅ SEARCH RESULTS AVAILABLE! 📡\n\n"
        output += f"📱 Search Results ({results_count} found)\n\n"
        
        for idx, item in enumerate(data_list, 1):
            output += f"Result {idx}:\n====================\n"
            output += f"📱 Mobile: {item.get('mobile', 'N/A')}\n"
            output += f"👤 Name: {item.get('name', 'N/A')}\n"
            output += f"👨 Father's Name: {item.get('fname', 'N/A')}\n"
            output += f"🏠 Address: {item.get('address', 'N/A')}\n"
            output += f"📞 Alternate: {item.get('alt', 'N/A')}\n"
            output += f"🌐 Circle: {item.get('circle', 'N/A')}\n"
            output += f"🆔 Aadhar: {item.get('aadhar', 'N/A')}\n"
            if item.get('email'):
                output += f"📧 Email: {item.get('email', 'N/A')}\n"
            output += "\n"
            
            alt = item.get('alt', None)
            if alt and len(str(alt)) == 10 and str(alt).isdigit():
                alt_output, error = perform_search(str(alt), user_id)
                if error:
                    output += f"🔄 Alt Search: {error}\n\n"
                elif alt_output:
                    output += alt_output + "\n\n"
        
        output += f"💳 Credits Remaining: {new_credits}\n"
        output += f"⏰ Searched on: {api_data.get('timestamp', 'N/A')}"
        
        msg = bot.send_message(chat_id, output, reply_markup=get_main_menu(), parse_mode='Markdown')
        logger.info(f"Search completed for user {user_id}, number {number}, {results_count} results")
        
    except Exception as e:
        try:
            bot.delete_message(chat_id, searching_msg.message_id)
        except:
            pass
        bot.send_message(chat_id, f"❌ Unexpected error: {str(e)[:50]}...")
        logger.error(f"Unexpected error in search: {e}")
        show_menu(chat_id)

def perform_search(number, user_id):
    user = get_user(user_id)
    if not user or user['credits'] < 2:
        return None, "❌ Insufficient credits for alt search."
    
    new_credits = user['credits'] - 2
    update_user(user_id, credits=new_credits)
    
    url = f"https://api.oblivionhunters.com/details?phone={number}&api_key={OSINT_API_KEY}"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        api_data = response.json()
        
        if api_data.get('status') != 'success':
            return None, "❌ Alt search failed."
        
        results_count = api_data.get('results_count', 0)
        data_list = api_data.get('data', [])
        
        if results_count == 0:
            return None, "❌ No results for alt number."
        
        output = f"Alt Search Results ({results_count} found):\n\n"
        
        for idx, item in enumerate(data_list, 1):
            output += f"Result {idx}:\n====================\n"
            output += f"📱 Mobile: {item.get('mobile', 'N/A')}\n"
            output += f"👤 Name: {item.get('name', 'N/A')}\n"
            output += f"👨 Father's Name: {item.get('fname', 'N/A')}\n"
            output += f"🏠 Address: {item.get('address', 'N/A')}\n"
            output += f"📞 Alternate: {item.get('alt', 'N/A')}\n"
            output += f"🌐 Circle: {item.get('circle', 'N/A')}\n"
            output += f"🆔 Aadhar: {item.get('aadhar', 'N/A')}\n"
            if item.get('email'):
                output += f"📧 Email: {item.get('email', 'N/A')}\n"
            output += "\n"
        
        output += f"💳 Credits: {new_credits}\n"
        output += f"⏰ Alt searched on: {api_data.get('timestamp', 'N/A')}"
        
        return output, None
    except Exception as e:
        logger.error(f"Alt search error for {number}: {e}")
        return None, f"❌ Alt search error: {str(e)[:50]}"

if __name__ == "__main__":
    logger.info("Starting OSINT BOT...")
    try:
        bot.infinity_polling(none_stop=True, interval=0, timeout=60)
    except Exception as e:
        logger.error(f"Polling error: {e}")