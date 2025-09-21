import telebot
from telebot import types
import requests
import sqlite3
import logging
import os
from config import TELEGRAM_BOT_TOKEN, BOT_USERNAME, OSINT_API_KEY, PAYMENT_BOT_USERNAME, SUPPORT_BOT_USERNAME, VERIFICATION_CHANNEL, CHANNEL_ID, ADMIN_USER_ID

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Database setup with connection pooling
def get_db_connection():
    conn = sqlite3.connect('users.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Initialize or update schema
    c = conn.cursor()
    try:
        c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, username TEXT, credits INTEGER, referrals INTEGER, status TEXT, first_time INTEGER, verified INTEGER, mirrors_created INTEGER DEFAULT 0)")
        c.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, number TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        c.execute("PRAGMA table_info(users)")
        columns = {row['name'] for row in c.fetchall()}
        if 'mirrors_created' not in columns:
            c.execute("ALTER TABLE users ADD COLUMN mirrors_created INTEGER DEFAULT 0")
            conn.commit()
            logger.info("Added 'mirrors_created' column to users table")
    except sqlite3.Error as e:
        logger.error(f"Database schema update error: {e}")
    finally:
        c.close()
    return conn

def get_user(user_id):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        if row:
            user_dict = dict(row)
            # Ensure mirrors_created is present with default 0 if missing
            if 'mirrors_created' not in user_dict:
                user_dict['mirrors_created'] = 0
            return user_dict
    except sqlite3.Error as e:
        logger.error(f"Database error in get_user: {e}")
    finally:
        c.close()
        conn.close()
    return None

def add_user(user_id, name, username):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (user_id, name, username, credits, referrals, status, first_time, verified, mirrors_created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (user_id, name, username, 4, 0, 'Guest', 1, 0, 0))
        conn.commit()
        logger.info(f"Added new user: {user_id}")
    except sqlite3.Error as e:
        logger.error(f"Database error in add_user: {e}")
    finally:
        c.close()
        conn.close()

def update_user(user_id, **kwargs):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        for key, value in kwargs.items():
            c.execute(f"UPDATE users SET {key} = ? WHERE user_id = ?", (value, user_id))
        conn.commit()
        logger.info(f"Updated user {user_id}: {kwargs}")
    except sqlite3.Error as e:
        logger.error(f"Database error in update_user: {e}")
    finally:
        c.close()
        conn.close()

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

def is_number_searched(user_id, number):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM history WHERE user_id = ? AND number = ?", (user_id, number))
        count = c.fetchone()[0]
        return count > 0
    except sqlite3.Error as e:
        logger.error(f"Database error in is_number_searched: {e}")
        return False
    finally:
        c.close()
        conn.close()

def add_to_history(user_id, number):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO history (user_id, number) VALUES (?, ?)", (user_id, number))
        conn.commit()
        logger.info(f"Added to history: user {user_id}, number {number}")
    except sqlite3.Error as e:
        logger.error(f"Database error in add_to_history: {e}")
    finally:
        c.close()
        conn.close()

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
    
    # Delete previous message only if it's not a search result
    try:
        if "SEARCH RESULTS AVAILABLE" not in call.message.text:
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
        bot.send_message(chat_id, "📱 Enter a 10-digit phone number to search:", reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(call.message, process_phone_number)
    
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
    if message.from_user.id != 7712183356:
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
        bot.register_next_step_handler(message, process_phone_number)
        return
    
    if user['credits'] < 2 and not is_number_searched(user_id, number):
        bot.send_message(chat_id, "❌ Low credits! Need 2 for search. Buy more via Purchase.")
        show_menu(chat_id)
        return
    
    searching_msg = bot.send_message(chat_id, "🔍 Searching... Please wait ⏳")
    
    if not is_number_searched(user_id, number):
        new_credits = user['credits'] - 2
        update_user(user_id, credits=new_credits)
        add_to_history(user_id, number)
    
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
            if alt and len(str(alt)) == 10 and str(alt).isdigit() and not is_number_searched(user_id, str(alt)):
                alt_output, _ = perform_search(str(alt), user_id)
                if alt_output:
                    output += alt_output + "\n\n"
                    add_to_history(user_id, str(alt))  # Log alt number if searched
        
        output += f"💳 Credits Remaining: {user['credits'] - 2 if not is_number_searched(user_id, number) else user['credits']}\n"
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
    # No credit deduction here, handled in process_phone_number
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
