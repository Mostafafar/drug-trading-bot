import os
import re
import time
import json
import logging
import random
import asyncio
import psycopg2
import traceback
import pandas as pd
from io import BytesIO
from pathlib import Path
from datetime import datetime
from enum import Enum, auto
from typing import Optional, Awaitable
from difflib import SequenceMatcher
import html

import requests
from telegram import (
    Update,
    Message,
    User,
    Chat,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    constants,
    error,
    InlineQueryResultArticle,
    InputTextMessageContent
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    CallbackContext,
    ExtBot,
    InlineQueryHandler,
    ChosenInlineResultHandler,
    PicklePersistence
)
from telegram.constants import ParseMode
from psycopg2 import sql, extras

# Constants and Configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Database Configuration
DB_CONFIG = {
    'dbname': 'drug_trading',
    'user': 'postgres',
    'password': 'f13821382',
    'host': 'localhost',
    'port': '5432'
}

# Path Configuration
current_dir = Path(__file__).parent
excel_file = current_dir / "DrugPrices.xlsx"
PHOTO_STORAGE = "registration_docs"
Path(PHOTO_STORAGE).mkdir(exist_ok=True)

# Admin Configuration
ADMIN_CHAT_ID = 6680287530
ADMINS = [ADMIN_CHAT_ID]  

# States Enum
# States Enum
class States(Enum):
    START = auto()
    REGISTER_PHARMACY_NAME = auto()
    REGISTER_FOUNDER_NAME = auto()
    REGISTER_NATIONAL_CARD = auto()
    REGISTER_LICENSE = auto()
    REGISTER_MEDICAL_CARD = auto()
    REGISTER_PHONE = auto()
    REGISTER_ADDRESS = auto()
    ADMIN_VERIFICATION = auto()
    SIMPLE_VERIFICATION = auto()
    SEARCH_DRUG = auto()
    SELECT_PHARMACY = auto()
    SELECT_DRUGS = auto()
    SELECT_QUANTITY = auto()
    CONFIRM_OFFER = auto()
    ADD_NEED_NAME = auto()
    ADD_NEED_QUANTITY = auto()
    SEARCH_DRUG_FOR_ADDING = auto()
    SELECT_DRUG_FOR_ADDING = auto()
    ADD_DRUG_DATE = auto()
    ADD_DRUG_QUANTITY = auto()
    ADMIN_UPLOAD_EXCEL = auto()
    EDIT_ITEM = auto()
    EDIT_DRUG = auto()
    EDIT_NEED = auto()
    SETUP_CATEGORIES = auto()
    PERSONNEL_VERIFICATION = auto()
    PERSONNEL_LOGIN = auto()
    COMPENSATION_SELECTION = auto()  # Add this line
    COMPENSATION_QUANTITY = auto()
    CONFIRM_TOTALS = auto()  
    ADMIN_VERIFY_PHARMACY_NAME = auto()
    SEARCH_DRUG_FOR_NEED = auto()
    ADD_DRUG_FROM_INLINE = auto() # اضافه کردن این خط

def get_db_connection(max_retries=3, retry_delay=1.0):
    """Get a database connection with retry logic"""
    conn = None
    last_error = None
    
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(
                dbname=DB_CONFIG['dbname'],
                user=DB_CONFIG['user'],
                password=DB_CONFIG['password'],
                host=DB_CONFIG['host'],
                port=DB_CONFIG['port']
            )
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.execute("SET TIME ZONE 'Asia/Tehran'")
            return conn
        except psycopg2.Error as e:
            last_error = e
            logger.error(f"DB connection attempt {attempt + 1} failed: {str(e)}")
            if conn:
                try:
                    conn.close()
                except:
                    pass
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))
    
    logger.critical(f"Failed to connect to DB after {max_retries} attempts")
    if last_error:
        raise last_error
    raise psycopg2.Error("Unknown database connection error")

async def initialize_db():
    """Initialize database tables and default data"""
    conn = None
    try:
        conn = get_db_connection()
        logger.info("Connected to database successfully")
        with conn.cursor() as cursor:
            # ایجاد جدول users
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    first_name TEXT,
                    last_name TEXT,
                    username TEXT,
                    phone TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_verified BOOLEAN DEFAULT FALSE,
                    verification_code TEXT,
                    verification_method TEXT,
                    is_admin BOOLEAN DEFAULT FALSE,
                    is_pharmacy_admin BOOLEAN DEFAULT FALSE,
                    is_personnel BOOLEAN DEFAULT FALSE,
                    simple_code TEXT,
                    creator_id BIGINT
                )
            ''')
            logger.info("Created users table")

            # ایجاد جدول pharmacies
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pharmacies (
                    user_id BIGINT PRIMARY KEY REFERENCES users(id),
                    name TEXT,
                    founder_name TEXT,
                    national_card_image TEXT,
                    license_image TEXT,
                    medical_card_image TEXT,
                    phone TEXT,
                    address TEXT,
                    admin_code TEXT UNIQUE,
                    verified BOOLEAN DEFAULT FALSE,
                    verified_at TIMESTAMP,
                    admin_id BIGINT REFERENCES users(id)
                )
            ''')
            logger.info("Created pharmacies table")

            # ایجاد جدول personnel_codes
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS personnel_codes (
                    code TEXT PRIMARY KEY,
                    creator_id BIGINT REFERENCES pharmacies(user_id),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                )
            ''')
            logger.info("Created personnel_codes table")

            # ایجاد بقیه جدول‌ها (مثل user_needs, drug_items, و غیره)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS drug_items (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(id),
                    name TEXT,
                    price TEXT,
                    date TEXT,
                    quantity INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logger.info("Created drug_items table")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_needs (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(id),
                    name TEXT,
                    description TEXT,
                    quantity INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logger.info("Created user_needs table")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS medical_categories (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE
                )
            ''')
            logger.info("Created medical_categories table")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_categories (
                    user_id BIGINT REFERENCES users(id),
                    category_id INTEGER REFERENCES medical_categories(id),
                    PRIMARY KEY (user_id, category_id)
                )
            ''')
            logger.info("Created user_categories table")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS offers (
                    id SERIAL PRIMARY KEY,
                    pharmacy_id BIGINT REFERENCES pharmacies(user_id),
                    buyer_id BIGINT REFERENCES users(id),
                    status TEXT DEFAULT 'pending',
                    total_price NUMERIC,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logger.info("Created offers table")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS offer_items (
                    id SERIAL PRIMARY KEY,
                    offer_id INTEGER REFERENCES offers(id),
                    drug_name TEXT,
                    price TEXT,
                    quantity INTEGER,
                    item_type TEXT DEFAULT 'drug'
                )
            ''')
            logger.info("Created offer_items table")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS compensation_items (
                    id SERIAL PRIMARY KEY,
                    offer_id INTEGER REFERENCES offers(id),
                    drug_id INTEGER REFERENCES drug_items(id),
                    quantity INTEGER
                )
            ''')
            logger.info("Created compensation_items table")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS match_notifications (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(id),
                    drug_id INTEGER REFERENCES drug_items(id),
                    need_id INTEGER REFERENCES user_needs(id),
                    similarity_score REAL,
                    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logger.info("Created match_notifications table")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_settings (
                    id SERIAL PRIMARY KEY,
                    excel_url TEXT,
                    last_updated TIMESTAMP
                )
            ''')
            logger.info("Created admin_settings table")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS exchanges (
                    id SERIAL PRIMARY KEY,
                    from_pharmacy_id BIGINT REFERENCES pharmacies(user_id),
                    to_pharmacy_id BIGINT REFERENCES pharmacies(user_id),
                    from_total NUMERIC,
                    to_total NUMERIC,
                    difference NUMERIC,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    accepted_at TIMESTAMP,
                    rejected_at TIMESTAMP
                )
            ''')
            logger.info("Created exchanges table")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS exchange_items (
                    id SERIAL PRIMARY KEY,
                    exchange_id INTEGER REFERENCES exchanges(id),
                    drug_id INTEGER REFERENCES drug_items(id),
                    drug_name TEXT,
                    price TEXT,
                    quantity INTEGER,
                    from_pharmacy BOOLEAN
                )
            ''')
            logger.info("Created exchange_items table")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS simple_codes (
                    code TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    used_by BIGINT[] DEFAULT array[]::BIGINT[],
                    max_uses INTEGER DEFAULT 5
                )
            ''')
            logger.info("Created simple_codes table")

            # فعال‌سازی pg_trgm
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            logger.info("Activated pg_trgm extension")

            # افزودن دسته‌بندی‌های پیش‌فرض
            default_categories = ['اعصاب', 'قلب', 'ارتوپد', 'زنان', 'گوارش', 'پوست', 'اطفال']
            for category in default_categories:
                cursor.execute('''
                    INSERT INTO medical_categories (name)
                    VALUES (%s)
                    ON CONFLICT (name) DO NOTHING
                ''', (category,))
            logger.info("Inserted default categories")

            # افزودن ادمین
            cursor.execute('''
                INSERT INTO users (id, is_admin, is_verified)
                VALUES (%s, TRUE, TRUE)
                ON CONFLICT (id) DO UPDATE SET is_admin = TRUE
            ''', (ADMIN_CHAT_ID,))
            logger.info("Inserted admin user")

            # تست جدول‌ها
            cursor.execute("SELECT 1 FROM users LIMIT 1")
            cursor.execute("SELECT 1 FROM user_needs LIMIT 1")
            cursor.execute("SELECT 1 FROM pharmacies LIMIT 1")
            logger.info("All tables tested successfully")

            conn.commit()
            logger.info("Database initialization completed successfully")
    
    except psycopg2.Error as e:
        logger.error(f"Database initialization error: {e}", exc_info=True)
        if conn:
            conn.rollback()
        raise
    
    finally:
        if conn:
            conn.close()
            logger.info("DB connection closed")
def format_button_text(text, max_line_length=25, max_lines=2):
    """
    Format text for Telegram button with proper line breaks
    Returns: Text formatted for button display
    """
    if not text:
        return ""
    
    # Split into words
    words = text.split()
    lines = []
    current_line = ""
    
    for word in words:
        if len(current_line) + len(word) + 1 <= max_line_length:
            current_line += f" {word}" if current_line else word
        else:
            lines.append(current_line)
            current_line = word
            if len(lines) >= max_lines:
                break
    
    if current_line and len(lines) < max_lines:
        lines.append(current_line)
    
    # Join with newlines and truncate if too long
    result = '\n'.join(lines)
    if len(result) > max_line_length * max_lines:
        result = result[:max_line_length * max_lines - 3] + "..."
    
    return result

async def ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ensure user exists in database"""
    user = update.effective_user
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('''
            INSERT INTO users (id, first_name, last_name, username, last_active)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET 
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                username = EXCLUDED.username,
                last_active = EXCLUDED.last_active
            ''', (user.id, user.first_name, user.last_name, user.username))
            conn.commit()
    except psycopg2.Error as e:
        logger.error(f"Error ensuring user: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

async def download_file(file, file_type: str, user_id: int) -> str:
    """Download a file from Telegram and save it locally"""
    try:
        file_name = f"{user_id}_{file_type}{os.path.splitext(file.file_path)[1]}"
        file_path = os.path.join(PHOTO_STORAGE, file_name)
        await file.download_to_drive(file_path)
        return file_path
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        raise

def load_drug_data() -> bool:
    """Load drug data from Excel file (local or GitHub)"""
    global drug_list
    
    try:
        if excel_file.exists():
            try:
                df = pd.read_excel(excel_file, sheet_name="Sheet1", engine='openpyxl')
                df = df.drop(columns=[col for col in df.columns if 'Unnamed' in col])
                drug_list = df[['name', 'price']].dropna().drop_duplicates().values.tolist()
                drug_list = [(str(name).strip(), str(price).strip()) for name, price in drug_list if str(name).strip()]
                logger.info(f"Loaded {len(drug_list)} drugs from local Excel file")
                return True
            except Exception as e:
                logger.error(f"Error reading local Excel file: {e}")
                
        github_url = "https://raw.githubusercontent.com/yourusername/yourrepo/main/DrugPrices.xlsx"
        response = requests.get(github_url)
        if response.status_code == 200:
            excel_data = BytesIO(response.content)
            df = pd.read_excel(excel_data, engine='openpyxl')
            df = df.drop(columns=[col for col in df.columns if 'Unnamed' in col])
            drug_list = df[['name', 'price']].dropna().drop_duplicates().values.tolist()
            drug_list = [(str(name).strip(), str(price).strip()) for name, price in drug_list if str(name).strip()]
            df.to_excel(excel_file, index=False, engine='openpyxl')
            logger.info(f"Loaded {len(drug_list)} drugs from GitHub and saved locally")
            return True
        
        logger.warning("Could not load drug data from either local file or GitHub")
        drug_list = []
        return False
        
    except Exception as e:
        logger.error(f"Error loading drug data: {e}")
        drug_list = []
        if excel_file.exists():
            backup_file = current_dir / f"DrugPrices_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            excel_file.rename(backup_file)
            logger.info(f"Created backup of corrupted file at {backup_file}")
        return False

def parse_price(price_str: str) -> float:
    """Convert price string to float by removing commas and currency symbols"""
    if not price_str:
        return 0.0
    try:
        # Remove any non-digit characters except decimal point
        cleaned = ''.join(c for c in price_str if c.isdigit() or c in ['.', ','])
        # Replace comma with nothing (for thousands separator)
        cleaned = cleaned.replace(',', '')
        return float(cleaned)
    except ValueError:
        return 0.0

def format_price(price: float) -> str:
    """Format price with comma separators every 3 digits from right"""
    try:
        # Convert to integer if it's a whole number
        if price.is_integer():
            return "{:,}".format(int(price)).replace(",", "،")  # Using Persian comma
        else:
            return "{:,.2f}".format(price).replace(",", "،")  # Using Persian comma for decimal numbers
    except (ValueError, TypeError):
        return "0"

def similarity(a: str, b: str) -> float:
    """Calculate similarity between two strings"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

async def check_for_matches(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Check for matches between user needs and available drugs"""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
            # Get user needs
            cursor.execute('''
            SELECT id, name, quantity 
            FROM user_needs 
            WHERE user_id = %s
            ''', (user_id,))
            needs = cursor.fetchall()
            
            if not needs:
                return
            
            # Get available drugs from other pharmacies
            cursor.execute('''
            SELECT di.id, di.name, di.price, di.quantity, 
                   u.id as pharmacy_id, 
                   p.name as pharmacy_name
            FROM drug_items di
            JOIN users u ON di.user_id = u.id
            JOIN pharmacies p ON u.id = p.user_id
            WHERE di.user_id != %s AND di.quantity > 0
            ORDER BY di.created_at DESC
            ''', (user_id,))
            drugs = cursor.fetchall()
            
            if not drugs:
                return
            
            # Find matches
            matches = []
            for need in needs:
                for drug in drugs:
                    # Check if already notified
                    cursor.execute('''
                    SELECT id FROM match_notifications 
                    WHERE user_id = %s AND drug_id = %s AND need_id = %s
                    ''', (user_id, drug['id'], need['id']))
                    if cursor.fetchone():
                        continue
                    
                    # Calculate similarity
                    sim_score = similarity(need['name'], drug['name'])
                    if sim_score >= 0.7:
                        matches.append({
                            'need': dict(need),
                            'drug': dict(drug),
                            'similarity': sim_score
                        })
            
            if not matches:
                return
            
            # Notify user about matches
            for match in matches:
                try:
                    message = (
                        "🔔 یک داروی مطابق با نیاز شما پیدا شد!\n\n"
                        f"نیاز شما: {match['need']['name']} (تعداد: {match['need']['quantity']})\n"
                        f"داروی موجود: {match['drug']['name']}\n"
                        f"داروخانه: {match['drug']['pharmacy_name']}\n"
                        f"قیمت: {match['drug']['price']}\n"
                        f"موجودی: {match['drug']['quantity']}\n\n"
                        "برای مشاهده جزئیات و تبادل، روی دکمه زیر کلیک کنید:"
                    )
                    
                    keyboard = [[
                        InlineKeyboardButton(
                            "مشاهده و تبادل",
                            callback_data=f"view_match_{match['drug']['id']}_{match['need']['id']}"
                        )
                    ]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        reply_markup=reply_markup
                    )
                    
                    # Record notification
                    cursor.execute('''
                    INSERT INTO match_notifications (
                        user_id, drug_id, need_id, similarity_score
                    ) VALUES (%s, %s, %s, %s)
                    ''', (
                        user_id,
                        match['drug']['id'],
                        match['need']['id'],
                        match['similarity']
                    ))
                    conn.commit()
                    
                except Exception as e:
                    logger.error(f"Failed to notify user: {e}")
                    if conn:
                        conn.rollback()
                        
    except Exception as e:
        logger.error(f"Error in check_for_matches: {e}")
    finally:
        if conn:
            conn.close()

async def clear_conversation_state(update: Update, context: ContextTypes.DEFAULT_TYPE, silent: bool = False):
    """Clear the conversation state while preserving essential trade and need data"""
    try:
        logger.info(f"Clearing conversation state for user {update.effective_user.id}")
        logger.info(f"Current keys in user_data: {list(context.user_data.keys())}")
        
        # 🔥 بررسی اینکه آیا کاربر در حال ثبت نیاز است یا مبادله
        current_state = context.user_data.get('_conversation_state')
        is_in_need_process = current_state in [
            States.SEARCH_DRUG_FOR_NEED, 
            States.ADD_NEED_QUANTITY,
            States.ADD_NEED_NAME,
        ]
        
        if is_in_need_process:
            # اگر در حال ثبت نیاز است، همه چیز را پاک کن
            context.user_data.clear()
            logger.info("Cleared all data for need registration process")
        else:
            # حفظ اطلاعات ضروری مربوط به مبادله
            trade_keys_to_preserve = [
                'selected_pharmacy_id', 'selected_pharmacy_name', 'selected_drug',
                'offer_items', 'comp_items', 'need_name', 'need_desc',
                'selected_drug_for_need', 'editing_need', 'edit_field',
                'editing_drug','user_needs_list', 'editing_needs_list', 'editing_need',
                'editing_drug', 'edit_field'  
            ]
            
            # ذخیره اطلاعات مبادله
            preserved_trade_data = {}
            for key in trade_keys_to_preserve:
                if key in context.user_data:
                    preserved_trade_data[key] = context.user_data[key]
                    logger.info(f"Preserving trade key: {key}")
            
            # پاک کردن کامل همه stateها
            context.user_data.clear()
            
            # بازگرداندن اطلاعات مبادله
            context.user_data.update(preserved_trade_data)
        
        # حذف state مکالمه
        context.user_data.pop('_conversation_state', None)
        
        logger.info(f"Final keys after clearing: {list(context.user_data.keys())}")
        
        if silent:
            return ConversationHandler.END
            
        # منوی اصلی
        main_keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        main_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
        
        try:
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(
                    text="به منوی اصلی بازگشتید:",
                    reply_markup=main_markup
                )
            else:
                await update.message.reply_text(
                    text="به منوی اصلی بازگشتید:",
                    reply_markup=main_markup
                )
        except Exception as e:
            logger.error(f"Error sending main menu: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="به منوی اصلی بازگشتید:",
                reply_markup=main_markup
            )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in clear_conversation_state: {e}", exc_info=True)
        
        # در صورت خطا، حداقل منوی اصلی را نشان دهد
        try:
            keyboard = [
                ['اضافه کردن دارو', 'جستجوی دارو'],
                ['لیست داروهای من', 'ثبت نیاز جدید'],
                ['لیست نیازهای من', 'ساخت کد پرسنل'],
                ['تنظیم شاخه‌های دارویی']
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="به منوی اصلی بازگشتید:",
                reply_markup=reply_markup
            )
        except Exception as inner_e:
            logger.error(f"Failed to send error recovery message: {inner_e}")
        
        return ConversationHandler.END

                

# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler with both registration options and verification check"""
    try:
        await ensure_user(update, context)
        
        # Check if user is banned
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                SELECT is_verified, is_pharmacy_admin, is_personnel
                FROM users 
                WHERE id = %s
                ''', (update.effective_user.id,))
                result = cursor.fetchone()
                
                if result and not result[0]:  # اگر کاربر اخراج شده باشد
                    # پاک کردن کیبورد قبلی
                    await update.message.reply_text(
                        "❌ حساب شما اخراج شده است.\n\n"
                        "برای استفاده مجدد از ربات، لطفا دوباره ثبت‌نام کنید.",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    
                    # نمایش گزینه‌های ثبت‌نام مجدد
                    keyboard = [
                        [InlineKeyboardButton("ثبت نام با تایید ادمین", callback_data="admin_verify")],
                        [InlineKeyboardButton("ورود با کد پرسنل", callback_data="personnel_login")],
                        [InlineKeyboardButton("ثبت نام با مدارک", callback_data="register")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        "لطفاً روش ورود را انتخاب کنید:",
                        reply_markup=reply_markup
                    )
                    return States.START
                    
        except Exception as e:
            logger.error(f"Error checking user status: {e}")
        finally:
            if conn:
                conn.close()

        # Check verification status
        is_verified = False
        is_pharmacy_admin = False
        is_personnel = False
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                SELECT u.is_verified, u.is_pharmacy_admin, u.is_personnel
                FROM users u
                WHERE u.id = %s
                ''', (update.effective_user.id,))
                result = cursor.fetchone()
                if result:
                    is_verified, is_pharmacy_admin, is_personnel = result
        except Exception as e:
            logger.error(f"Database error in start: {e}")
        finally:
            if conn:
                conn.close()

        if not is_verified:
            # Show registration options for unverified users
            keyboard = [
                [InlineKeyboardButton("ثبت نام با تایید ادمین", callback_data="admin_verify")],
                [InlineKeyboardButton("ورود با کد پرسنل", callback_data="personnel_login")],
                [InlineKeyboardButton("ثبت نام با مدارک", callback_data="register")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "به ربات تبادل دارو خوش آمدید!\n"
                "برای استفاده از ربات لطفاً روش ورود را انتخاب کنید:",
                reply_markup=reply_markup
            )
            return States.START

        # For verified users - show appropriate main menu
        context.application.create_task(check_for_matches(update.effective_user.id, context))
        
        # Different menu for pharmacy admin vs regular users vs personnel
        if is_pharmacy_admin:
            keyboard = [
                ['اضافه کردن دارو', 'جستجوی دارو'],
                ['لیست داروهای من', 'ثبت نیاز جدید'],
                ['لیست نیازهای من', 'ساخت کد پرسنل'],
                ['تنظیم شاخه‌های دارویی']
            ]
            welcome_msg = "به پنل مدیریت داروخانه خوش آمدید."
        elif is_personnel:
            keyboard = [
                ['اضافه کردن دارو', 'جستجوی دارو'],
                ['لیست داروهای من', 'ثبت نیاز جدید'],
                ['لیست نیازهای من']
            ]
            welcome_msg = "به پنل پرسنل خوش آمدید."
        else:
            keyboard = [
                ['اضافه کردن دارو', 'جستجوی دارو'],
                ['لیست داروهای من', 'ثبت نیاز جدید'],
                ['لیست نیازهای من']
            ]
            welcome_msg = "حساب کاربری شما فعال است."
            
        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            one_time_keyboard=True,
            resize_keyboard=True
        )
        
        await update.message.reply_text(
            f"{welcome_msg}\n\nلطفاً یک گزینه را انتخاب کنید:",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in start handler: {e}")
        await update.message.reply_text(
            "خطایی در پردازش درخواست شما رخ داد. لطفاً دوباره تلاش کنید."
        )
        return ConversationHandler.END
async def generate_personnel_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ساخت کد پرسنل توسط داروخانه تایید شده"""
    await clear_conversation_state(update, context)
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # بررسی تایید بودن داروخانه
            cursor.execute('''
            SELECT 1 FROM pharmacies 
            WHERE user_id = %s AND verified = TRUE
            ''', (update.effective_user.id,))
            
            if not cursor.fetchone():
                await update.message.reply_text("❌ فقط داروخانه‌های تایید شده می‌توانند کد ایجاد کنند.")
                return

            # ساخت کد 6 رقمی
            code = str(random.randint(100000, 999999))
            
            # ذخیره کد
            cursor.execute('''
            INSERT INTO personnel_codes (code, creator_id)
            VALUES (%s, %s)
            ON CONFLICT (code) DO NOTHING
            ''', (code, update.effective_user.id))
            conn.commit()
            
            await update.message.reply_text(
                f"✅ کد پرسنل شما:\n\n{code}\n\n"
                "این کد نامحدود کاربر می‌تواند استفاده کند."
            )
    except Exception as e:
        logger.error(f"Error generating personnel code: {e}")
        await update.message.reply_text("خطا در ساخت کد پرسنل")
    finally:
        if conn:
            conn.close()

async def personnel_login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع فرآیند ورود با کد پرسنل"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Create a simple inline keyboard with a back button
        keyboard = [
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "لطفا کد پرسنل خود را وارد کنید:",
            reply_markup=reply_markup
        )
        return States.PERSONNEL_LOGIN
        
    except Exception as e:
        logger.error(f"Error in personnel_login_start: {e}")
        try:
            # Try to send a new message if editing fails
            if update.callback_query:
                await context.bot.send_message(
                    chat_id=update.callback_query.message.chat_id,
                    text="لطفا کد پرسنل خود را وارد کنید:",
                    reply_markup=ReplyKeyboardRemove()
                )
            elif update.message:
                await update.message.reply_text(
                    "لطفا کد پرسنل خود را وارد کنید:",
                    reply_markup=ReplyKeyboardRemove()
                )
            return States.PERSONNEL_LOGIN
        except Exception as e2:
            logger.error(f"Failed to handle error in personnel_login_start: {e2}")
            return ConversationHandler.END



async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Central callback query handler"""
    try:
        query = update.callback_query
        await query.answer()  # Always answer the callback query first
        
        if not query.data:
            logger.warning("Empty callback data received")
            return

        # Handle restart after ban
        if query.data == "restart_after_ban":
            # پاک کردن پیام قبلی
            try:
                await query.delete_message()
            except:
                pass
            
            # نمایش گزینه‌های ثبت‌نام مجدد
            keyboard = [
                [InlineKeyboardButton("ثبت نام با تایید ادمین", callback_data="admin_verify")],
                [InlineKeyboardButton("ورود با کد پرسنل", callback_data="personnel_login")],
                [InlineKeyboardButton("ثبت نام با مدارک", callback_data="register")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text="❌ حساب شما اخراج شده است.\n\n"
                     "برای استفاده مجدد از ربات، لطفا یکی از روش‌های زیر را انتخاب کنید:",
                reply_markup=reply_markup
            )
            return States.START

        # Handle back button - بازگشت مستقیم به لیست داروها
        elif query.data == "back":
            try:
                await query.delete_message()
            except:
                pass
            # ایجاد یک پیام جدید برای فراخوانی list_my_drugs
            fake_update = Update(
                update_id=update.update_id,
                message=Message(
                    message_id=update.update_id,
                    date=datetime.now(),
                    chat=query.message.chat,
                    text="/list_drugs"
                )
            )
            return await list_my_drugs(fake_update, context)
            
        # Handle different callback patterns
        elif query.data.startswith("approve_user_"):
            return await approve_user(update, context)
        elif query.data.startswith("reject_user_"):
            return await reject_user(update, context)
        elif query.data.startswith("add_drug_"):
        # بقیه هندلرهای موجود...
            return await handle_add_drug_callback(update, context)
        # بقیه هندلرهای موجود...
        # ...

        # Handle different callback patterns
        if query.data == "back":
            return await handle_back(update, context)
        elif query.data == "cancel":
            return await cancel(update, context)
        elif query.data == "back_to_main":  # <-- این خط را اضافه کنید
            return await clear_conversation_state(update, context)
        elif query.data.startswith("pharmacy_"):
            return await select_pharmacy(update, context)
        elif query.data.startswith("offer_"):
            return await handle_offer_response(update, context)
        elif query.data.startswith("togglecat_"):
            return await toggle_category(update, context)
        elif query.data == "save_categories":
            return await save_categories(update, context)
        elif query.data == "admin_verify":
            return await admin_verify_start(update, context)
        elif query.data == "register":
            return await register_pharmacy_name(update, context)
        elif query.data == "simple_verify":
            return await simple_verify_start(update, context)
        elif query.data.startswith("view_match_"):
            return await handle_match_notification(update, context)
        elif query.data == "edit_drugs":
            return await edit_drugs(update, context)
        elif query.data.startswith("edit_drug_"):
            return await edit_drug_item(update, context)
        elif query.data in ["edit_date", "edit_quantity", "delete_drug"]:
            return await handle_drug_edit_action(update, context)
        elif query.data == "back_to_drugs_list":
            return await list_my_drugs(update, context)
        elif query.data == "confirm_delete":
            return await handle_drug_deletion(update, context)
        elif query.data == "cancel_delete":
            return await edit_drug_item(update, context)
        elif query.data == "edit_needs":
            return await edit_needs(update, context)
        elif query.data.startswith("edit_need_"):
            return await edit_need_item(update, context)
        elif query.data in ["edit_need_name", "edit_need_desc", "edit_need_quantity", "delete_need"]:
            return await handle_need_edit_action(update, context)
        elif query.data == "confirm_need_delete":
            return await handle_need_deletion(update, context)
        elif query.data == "cancel_need_delete":
            return await edit_need_item(update, context)
        elif query.data == "back_to_list":
            return await edit_drugs(update, context)
        elif query.data == "back_to_needs_list":
            return await edit_needs(update, context)
        elif query.data.startswith("select_drug_"):
            return await select_drug_for_adding(update, context)
        elif query.data == "back_to_search":
            return await search_drug_for_adding(update, context)
        elif query.data == "back_to_drug_selection":
            return await select_drug_for_adding(update, context)
        elif query.data == "finish_selection":
            return await confirm_totals(update, context)
        elif query.data == "compensate":
            return await handle_compensation_selection(update, context)
        elif query.data.startswith("comp_"):
            return await handle_compensation_selection(update, context)
        elif query.data == "comp_finish":
            return await confirm_totals(update, context)
        elif query.data == "back_to_totals":
            return await confirm_totals(update, context)
        elif query.data == "back_to_items":
            return await show_two_column_selection(update, context)
        elif query.data == "back_to_pharmacies":
            return await select_pharmacy(update, context)
        elif query.data == "confirm_totals":
            return await confirm_totals(update, context)
        elif query.data == "edit_selection":
            return await show_two_column_selection(update, context)
        
        logger.warning(f"Unhandled callback data: {query.data}")
        await query.edit_message_text("این گزینه در حال حاضر قابل استفاده نیست.")
        
    except Exception as e:
        logger.error(f"Error processing callback {query.data}: {e}")
        try:
            await query.edit_message_text("خطایی در پردازش درخواست شما رخ داد.")
        except Exception as e:
            logger.error(f"Failed to edit message: {e}")
                
    except Exception as e:
        logger.error(f"Error in callback_handler: {e}")
        try:
            if update.callback_query:
                await update.callback_query.answer("خطایی رخ داد. لطفا دوباره تلاش کنید.", show_alert=True)
        except:
            pass


async def handle_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بهبود هندلر بازگشت با مدیریت بهتر state"""
    try:
        if update.callback_query:
            await update.callback_query.answer()
            chat_id = update.callback_query.message.chat_id
        else:
            chat_id = update.message.chat_id
        
        # پاک کردن state مربوط به عملیات جاری
        keys_to_remove = [
            'selected_pharmacy_id', 'selected_pharmacy_name', 
            'offer_items', 'comp_items', 'current_selection',
            'current_list', 'page_target', 'page_mine',
            'selected_drug', 'expiry_date', 'drug_quantity',
            'need_name', 'need_desc', 'editing_drug', 'editing_need',
            'edit_field', 'match_drug', 'match_need'
        ]
        
        for key in keys_to_remove:
            context.user_data.pop(key, None)
        
        # نمایش منوی اصلی
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text="به منوی اصلی بازگشتید. لطفاً یک گزینه را انتخاب کنید:",
            reply_markup=reply_markup
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in handle_back: {e}")
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="خطایی در بازگشت رخ داد. به منوی اصلی بازگشتید."
            )
        except:
            pass
        return ConversationHandler.END



async def simple_verify_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start simple verification process"""
    try:
        query = update.callback_query
        await query.answer()
        
        try:
            await query.edit_message_text(
                "لطفا کد تایید 5 رقمی خود را وارد کنید:",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="لطفا کد تایید 5 رقمی خود را وارد کنید:",
                reply_markup=ReplyKeyboardRemove()
            )
        return States.SIMPLE_VERIFICATION
    except Exception as e:
        logger.error(f"Error in simple_verify_start: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def simple_verify_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify simple 5-digit code"""
    try:
        user_code = update.message.text.strip()
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Check if code exists and has remaining uses
                cursor.execute('''
                UPDATE simple_codes 
                SET used_by = array_append(used_by, %s)
                WHERE code = %s AND array_length(used_by, 1) < max_uses
                RETURNING code
                ''', (update.effective_user.id, user_code))
                result = cursor.fetchone()
                
                if result:
                    # Mark user as verified
                    cursor.execute('''
                    UPDATE users 
                    SET is_verified = TRUE, 
                        verification_method = 'simple_code',
                        simple_code = %s
                    WHERE id = %s
                    ''', (user_code, update.effective_user.id))
                    
                    conn.commit()
                    
                    await update.message.reply_text(
                        "✅ حساب شما با موفقیت تایید شد!\n\n"
                        "شما می‌توانید از امکانات پایه ربات استفاده کنید."
                    )
                    return await start(update, context)
                else:
                    await update.message.reply_text("کد تایید نامعتبر است یا به حداکثر استفاده رسیده است.")
                    return States.SIMPLE_VERIFICATION
                    
        except Exception as e:
            logger.error(f"Error in simple verification: {e}")
            if conn:
                conn.rollback()
            await update.message.reply_text("خطا در تایید حساب. لطفا دوباره تلاش کنید.")
            return ConversationHandler.END
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in simple_verify_code: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END


async def admin_verify_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست ثبت نام با تایید ادمین"""
    try:
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "لطفا نام داروخانه خود را وارد کنید:",
            reply_markup=None
        )
        
        return States.ADMIN_VERIFY_PHARMACY_NAME
        
    except Exception as e:
        logger.error(f"Error in admin_verify_start: {e}")
        try:
            await query.edit_message_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
        except:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="خطایی رخ داد. لطفا دوباره تلاش کنید."
            )
        return ConversationHandler.END
async def admin_verify_pharmacy_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت نام داروخانه برای تایید ادمین"""
    try:
        pharmacy_name = update.message.text
        context.user_data['pharmacy_name'] = pharmacy_name
        
        # درخواست شماره تلفن از کاربر
        keyboard = [[KeyboardButton("اشتراک گذاری شماره تلفن", request_contact=True)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            f"نام داروخانه: {pharmacy_name}\n\nلطفا شماره تلفن خود را به اشتراک بگذارید:",
            reply_markup=reply_markup
        )
        
        return States.REGISTER_PHONE
        
    except Exception as e:
        logger.error(f"Error in admin_verify_pharmacy_name: {e}")
        await update.message.reply_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
async def receive_phone_for_admin_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت شماره تلفن برای تایید ادمین"""
    try:
        if update.message.contact:
            phone_number = update.message.contact.phone_number
        else:
            keyboard = [[KeyboardButton("📞 اشتراک گذاری شماره تلفن", request_contact=True)]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(
                "❌ لطفا فقط از دکمه اشتراک گذاری استفاده کنید:",
                reply_markup=reply_markup
            )
            return States.REGISTER_PHONE
        
        user = update.effective_user
        context.user_data['phone'] = phone_number
        
        # ذخیره شماره تلفن در دیتابیس
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                UPDATE users SET phone = %s 
                WHERE id = %s
                ''', (phone_number, user.id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error saving phone: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
        
        # ارسال اطلاعات به ادمین با دکمه‌های تایید/رد
        admin_message = (
            f"📌 درخواست ثبت نام جدید:\n\n"
            f"👤 نام: {user.full_name}\n"
            f"🆔 آیدی: {user.id}\n"
            f"📌 یوزرنیم: @{user.username or 'ندارد'}\n"
            f"📞 تلفن: {phone_number}\n\n"
            f"لطفا این کاربر را تایید یا رد کنید:"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ تایید کاربر", callback_data=f"approve_user_{user.id}"),
                InlineKeyboardButton("❌ رد کاربر", callback_data=f"reject_user_{user.id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_message,
            reply_markup=reply_markup
        )
        
        await update.message.reply_text(
            "اطلاعات شما برای تایید به ادمین ارسال شد. پس از تایید می‌توانید از ربات استفاده کنید.",
            reply_markup=ReplyKeyboardRemove()
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in receive_phone_for_admin_verify: {e}")
        await update.message.reply_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END


async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید کاربر توسط ادمین"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = int(query.data.split("_")[2])
        logger.info(f"شروع فرآیند تایید برای کاربر {user_id}")
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # بررسی وجود کاربر
                cursor.execute('SELECT id, is_verified FROM users WHERE id = %s', (user_id,))
                user_data = cursor.fetchone()
                
                if not user_data:
                    logger.error(f"کاربر {user_id} یافت نشد")
                    await query.edit_message_text(f"❌ کاربر با آیدی {user_id} در سیستم ثبت نشده است")
                    return
                
                if user_data[1]:  # اگر کاربر از قبل تایید شده باشد
                    logger.warning(f"کاربر {user_id} از قبل تایید شده است")
                    await query.edit_message_text(f"⚠️ کاربر {user_id} قبلاً تایید شده بود")
                    return
                
                # تایید کاربر
                cursor.execute('''
                UPDATE users 
                SET is_verified = TRUE, 
                    is_pharmacy_admin = TRUE,
                    verification_method = 'admin_approved'
                WHERE id = %s
                RETURNING id
                ''', (user_id,))
                
                if not cursor.fetchone():
                    logger.error(f"خطا در به‌روزرسانی کاربر {user_id}")
                    await query.edit_message_text("خطا در به‌روزرسانی وضعیت کاربر")
                    return
                
                # ایجاد/به‌روزرسانی داروخانه
                cursor.execute('''
                INSERT INTO pharmacies (user_id, verified, verified_at, admin_id)
                VALUES (%s, TRUE, CURRENT_TIMESTAMP, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    verified = TRUE,
                    verified_at = CURRENT_TIMESTAMP,
                    admin_id = EXCLUDED.admin_id
                RETURNING user_id
                ''', (user_id, update.effective_user.id))
                
                if not cursor.fetchone():
                    logger.error(f"خطا در ثبت داروخانه برای کاربر {user_id}")
                    await query.edit_message_text("خطا در ثبت اطلاعات داروخانه")
                    conn.rollback()
                    return
                
                conn.commit()
                logger.info(f"کاربر {user_id} با موفقیت تایید شد")
                
                # ارسال پیام به کاربر با کیبورد مدیریت
                try:
                    # کیبورد مدیریت برای داروخانه
                    keyboard = [
                        ['اضافه کردن دارو', 'جستجوی دارو'],
                        ['لیست داروهای من', 'ثبت نیاز جدید'],
                        ['لیست نیازهای من', 'ساخت کد پرسنل'],
                        ['تنظیم شاخه‌های دارویی']
                    ]
                    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                    
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="✅ حساب شما توسط ادمین تایید شد!\n\n"
                             "شما اکنون می‌توانید از تمام امکانات مدیریت داروخانه استفاده کنید.",
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    logger.error(f"خطا در ارسال پیام به کاربر {user_id}: {str(e)}")
                
                await query.edit_message_text(
                    f"✅ کاربر {user_id} با موفقیت تایید شد و به عنوان مدیر داروخانه تنظیم شد."
                )
                
        except Exception as e:
            logger.error(f"خطا در تایید کاربر {user_id}: {str(e)}")
            await query.edit_message_text(f"خطا در تایید کاربر: {str(e)}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
                
    except Exception as e:
        logger.error(f"خطای سیستمی در approve_user: {str(e)}")
        try:
            await query.edit_message_text("خطای سیستمی در پردازش درخواست")
        except:
            pass
async def reject_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رد کاربر توسط ادمین"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = int(query.data.split("_")[2])
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # حذف کاربر از لیست انتظار تایید
                cursor.execute('''
                DELETE FROM pharmacies 
                WHERE user_id = %s AND verified = FALSE
                ''', (user_id,))
                
                conn.commit()
                
                # ارسال پیام به کاربر
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="متاسفانه درخواست ثبت نام شما رد شد.\n"
                             "برای اطلاعات بیشتر با پشتیبانی تماس بگیرید."
                    )
                except Exception as e:
                    logger.error(f"Failed to notify user: {e}")
                
                await query.edit_message_text(
                    f"❌ کاربر {user_id} رد شد."
                )
                
        except Exception as e:
            logger.error(f"Error rejecting user: {e}")
            await query.edit_message_text("خطا در رد کاربر.")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
                
    except Exception as e:
        logger.error(f"Error in reject_user: {e}")
        try:
            await query.edit_message_text("خطایی در رد کاربر رخ داد.")
        except:
            pass


async def generate_personnel_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ساخت کد پرسنل توسط داروخانه تایید شده"""
    await clear_conversation_state(update, context)
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # بررسی تایید بودن داروخانه
            cursor.execute('''
            SELECT 1 FROM pharmacies 
            WHERE user_id = %s AND verified = TRUE
            ''', (update.effective_user.id,))
            
            if not cursor.fetchone():
                await update.message.reply_text("❌ فقط داروخانه‌های تایید شده می‌توانند کد ایجاد کنند.")
                return

            # ساخت کد 6 رقمی
            code = str(random.randint(100000, 999999))
            
            # ذخیره کد
            cursor.execute('''
            INSERT INTO personnel_codes (code, creator_id)
            VALUES (%s, %s)
            ''', (code, update.effective_user.id))
            conn.commit()
            
            await update.message.reply_text(
                f"✅ کد پرسنل شما:\n\n{code}\n\n"
                "این کد نامحدود کاربر می‌تواند استفاده کند."
            )
    except Exception as e:
        logger.error(f"Error generating personnel code: {e}")
        await update.message.reply_text("خطا در ساخت کد پرسنل")
    finally:
        if conn:
            conn.close()

async def verify_personnel_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify personnel code"""
    try:
        code = update.message.text.strip()
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # First verify the personnel code exists
                cursor.execute('''
                SELECT creator_id FROM personnel_codes 
                WHERE code = %s
                ''', (code,))
                
                result = cursor.fetchone()
                if not result:
                    await update.message.reply_text("❌ کد نامعتبر است.")
                    return States.PERSONNEL_LOGIN
                    
                creator_id = result[0]
                
                # Update user record
                cursor.execute('''
                UPDATE users 
                SET is_verified = TRUE, 
                    is_personnel = TRUE,
                    creator_id = %s,
                    verification_method = 'personnel_code'
                WHERE id = %s
                ''', (creator_id, update.effective_user.id))
                
                conn.commit()
                
                await update.message.reply_text(
                    "✅ ورود با کد پرسنل موفقیت آمیز بود!\n\n"
                    "شما می‌توانید:\n"
                    "- دارو اضافه/ویرایش کنید\n"
                    "- نیازها را مدیریت کنید\n\n"
                    "⚠️ توجه: امکان انجام تبادل را ندارید.",
                    reply_markup=ReplyKeyboardRemove()
                )
                
                # Return to main menu
                keyboard = [
                    ['اضافه کردن دارو', 'جستجوی دارو'],
                    ['لیست داروهای من', 'ثبت نیاز جدید'],
                    ['لیست نیازهای من']
                ]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="به منوی اصلی پرسنل خوش آمدید:",
                    reply_markup=reply_markup
                )
                
                return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error verifying personnel code: {e}")
            await update.message.reply_text("خطا در تایید کد پرسنل")
            return States.PERSONNEL_LOGIN
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in verify_personnel_code: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return States.PERSONNEL_LOGIN
async def approve_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید کاربر از طریق callback"""
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data.startswith("approve_"):
            user_id = int(query.data.split("_")[1])
            await approve_user(update, context)
        elif query.data.startswith("reject_"):
            user_id = int(query.data.split("_")[1])
            await reject_user(update, context)
            
    except Exception as e:
        logger.error(f"Error in approve_user_callback: {e}")
        try:
            await query.edit_message_text("خطا در پردازش درخواست")
        except:
            pass
# Registration Handlers
async def register_pharmacy_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start pharmacy registration - get pharmacy name"""
    try:
        query = update.callback_query
        await query.answer()
        
        try:
            await query.edit_message_text(
                "لطفا نام داروخانه را وارد کنید:",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="لطفا نام داروخانه را وارد کنید:",
                reply_markup=ReplyKeyboardRemove()
            )
        return States.REGISTER_PHARMACY_NAME
    except Exception as e:
        logger.error(f"Error in register_pharmacy_name: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def register_founder_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get founder name in registration process"""
    try:
        pharmacy_name = update.message.text
        context.user_data['pharmacy_name'] = pharmacy_name
        
        await update.message.reply_text(
            "لطفا نام مالک/مدیر داروخانه را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.REGISTER_FOUNDER_NAME
    except Exception as e:
        logger.error(f"Error in register_founder_name: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def register_national_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get national card photo in registration process - فقط عکس قبول کند"""
    try:
        if not (update.message.photo or (update.message.document and update.message.document.mime_type.startswith('image/'))):
            await update.message.reply_text("❌ لطفا فقط تصویر کارت ملی را ارسال کنید.")
            return States.REGISTER_NATIONAL_CARD
        
        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
        else:
            photo_file = await update.message.document.get_file()
        
        file_path = await download_file(photo_file, "national_card", update.effective_user.id)
        context.user_data['national_card'] = file_path
        
        await update.message.reply_text(
            "✅ تصویر کارت ملی دریافت شد.\n\nلطفا تصویر پروانه داروخانه را ارسال کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.REGISTER_LICENSE
    except Exception as e:
        logger.error(f"Error in register_national_card: {e}")
        await update.message.reply_text("خطایی در دریافت تصویر رخ داد. لطفا دوباره تلاش کنید.")
        return States.REGISTER_NATIONAL_CARD

async def register_license(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get license photo in registration process - فقط عکس قبول کند"""
    try:
        if not (update.message.photo or (update.message.document and update.message.document.mime_type.startswith('image/'))):
            await update.message.reply_text("❌ لطفا فقط تصویر پروانه داروخانه را ارسال کنید.")
            return States.REGISTER_LICENSE
        
        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
        else:
            photo_file = await update.message.document.get_file()
        
        file_path = await download_file(photo_file, "license", update.effective_user.id)
        context.user_data['license'] = file_path
        
        await update.message.reply_text(
            "✅ تصویر پروانه داروخانه دریافت شد.\n\nلطفا تصویر کارت نظام پزشکی را ارسال کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.REGISTER_MEDICAL_CARD
    except Exception as e:
        logger.error(f"Error in register_license: {e}")
        await update.message.reply_text("خطایی در دریافت تصویر رخ داد. لطفا دوباره تلاش کنید.")
        return States.REGISTER_LICENSE

async def register_medical_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get medical card photo in registration process - فقط عکس قبول کند"""
    try:
        if not (update.message.photo or (update.message.document and update.message.document.mime_type.startswith('image/'))):
            await update.message.reply_text("❌ لطفا فقط تصویر کارت نظام پزشکی را ارسال کنید.")
            return States.REGISTER_MEDICAL_CARD
        
        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
        else:
            photo_file = await update.message.document.get_file()
        
        file_path = await download_file(photo_file, "medical_card", update.effective_user.id)
        context.user_data['medical_card'] = file_path
        
        keyboard = [[KeyboardButton("📞 اشتراک گذاری شماره تلفن", request_contact=True)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            "✅ تصویر کارت نظام پزشکی دریافت شد.\n\nلطفا شماره تلفن خود را با استفاده از دکمه زیر ارسال کنید:",
            reply_markup=reply_markup
        )
        return States.REGISTER_PHONE
    except Exception as e:
        logger.error(f"Error in register_medical_card: {e}")
        await update.message.reply_text("خطایی در دریافت تصویر رخ داد. لطفا دوباره تلاش کنید.")
        return States.REGISTER_MEDICAL_CARD

async def register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get phone number using share contact button"""
    try:
        if not update.message.contact:
            await update.message.reply_text(
                "❌ لطفا از دکمه اشتراک گذاری شماره تلفن استفاده کنید:",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("📞 اشتراک گذاری شماره تلفن", request_contact=True)]],
                    resize_keyboard=True,
                    one_time_keyboard=True
                )
            )
            return States.REGISTER_PHONE
        
        phone_number = update.message.contact.phone_number
        context.user_data['phone'] = phone_number
        
        # ذخیره شماره تلفن در دیتابیس
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                UPDATE users SET phone = %s 
                WHERE id = %s
                ''', (phone_number, update.effective_user.id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error saving phone: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
        
        # درخواست آدرس
        await update.message.reply_text(
            "✅ شماره تلفن دریافت شد.\n\nلطفا آدرس کامل داروخانه را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.REGISTER_ADDRESS
        
    except Exception as e:
        logger.error(f"Error in register_phone: {e}")
        await update.message.reply_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
        return States.REGISTER_MEDICAL_CARD
async def register_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get address in registration process"""
    try:
        address = update.message.text
        context.user_data['address'] = address
        
        # ذخیره آدرس در دیتابیس
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                INSERT INTO pharmacies (user_id, name, founder_name, address, phone)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    founder_name = EXCLUDED.founder_name,
                    address = EXCLUDED.address,
                    phone = EXCLUDED.phone
                ''', (
                    update.effective_user.id,
                    context.user_data.get('pharmacy_name'),
                    context.user_data.get('founder_name'),
                    address,
                    context.user_data.get('phone')
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Error saving address: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
        
        # ارسال اطلاعات کامل به ادمین
        await send_complete_registration_to_admin(update, context)
        
        await update.message.reply_text(
            "✅ اطلاعات شما برای تایید به ادمین ارسال شد.\n\n"
            "پس از تایید، می‌توانید از امکانات مدیریت داروخانه استفاده کنید.",
            reply_markup=ReplyKeyboardRemove()
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in register_address: {e}")
        await update.message.reply_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
        return States.REGISTER_PHONE
async def ask_for_national_card_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست مجدد عکس کارت ملی"""
    await update.message.reply_text("❌ لطفا فقط تصویر کارت ملی را ارسال کنید.")
    return States.REGISTER_NATIONAL_CARD

async def ask_for_license_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست مجدد عکس پروانه داروخانه"""
    await update.message.reply_text("❌ لطفا فقط تصویر پروانه داروخانه را ارسال کنید.")
    return States.REGISTER_LICENSE

async def ask_for_medical_card_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست مجدد عکس کارت نظام پزشکی"""
    await update.message.reply_text("❌ لطفا فقط تصویر کارت نظام پزشکی را ارسال کنید.")
    return States.REGISTER_MEDICAL_CARD

async def ask_for_phone_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست مجدد شماره تلفن"""
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📞 اشتراک گذاری شماره تلفن", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await update.message.reply_text(
        "❌ لطفا از دکمه اشتراک گذاری شماره تلفن استفاده کنید:",
        reply_markup=keyboard
    )
    return States.REGISTER_PHONE
async def send_registration_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send registration data to admin"""
    try:
        user_data = context.user_data
        user = update.effective_user
        
        message = f"📋 درخواست ثبت نام جدید\n\n"
        message += f"👤 کاربر: {user.full_name} (@{user.username})\n"
        message += f"🆔 ID: {user.id}\n"
        message += f"🏢 نام داروخانه: {user_data.get('pharmacy_name', 'نامشخص')}\n"
        message += f"👨‍💼 نام مسئول: {user_data.get('founder_name', 'نامشخص')}\n\n"
        message += f"📞 شماره تلفن: در انتظار ارسال..."
        
        # ارسال پیام به ادمین‌ها
        for admin_id in ADMINS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=message,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⏳ در انتظار اطلاعات بیشتر", callback_data="pending_info")]
                    ])
                )
            except Exception as e:
                logger.error(f"Error sending to admin {admin_id}: {e}")
                
    except Exception as e:
        logger.error(f"Error in send_registration_to_admin: {e}")


async def send_complete_registration_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send complete registration data to admin with inline buttons"""
    try:
        user_data = context.user_data
        user = update.effective_user
        
        message = f"✅ درخواست ثبت نام کامل شد\n\n"
        message += f"👤 کاربر: {user.full_name} (@{user.username or 'ندارد'})\n"
        message += f"🆔 ID: {user.id}\n"
        message += f"🏢 نام داروخانه: {user_data.get('pharmacy_name', 'نامشخص')}\n"
        message += f"👨‍💼 نام مسئول: {user_data.get('founder_name', 'نامشخص')}\n"
        message += f"📞 شماره تلفن: {user_data.get('phone', 'نامشخص')}\n"
        message += f"📍 آدرس: {user_data.get('address', 'نامشخص')}\n\n"
        message += "لطفا این کاربر را تایید یا رد کنید:"
        
        try:
            # ارسال پیام اصلی
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=message,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ تایید کاربر", callback_data=f"approve_user_{user.id}"),
                        InlineKeyboardButton("❌ رد کاربر", callback_data=f"reject_user_{user.id}")
                    ]
                ])
            )
            
            # ارسال تصاویر
            for file_type in ['national_card', 'license', 'medical_card']:
                if file_type in user_data:
                    try:
                        with open(user_data[file_type], 'rb') as photo:
                            await context.bot.send_photo(
                                chat_id=ADMIN_CHAT_ID,
                                photo=photo,
                                caption=f"📄 {file_type.replace('_', ' ').title()}"
                            )
                    except Exception as e:
                        logger.error(f"Error sending {file_type} to admin: {e}")
                        
        except Exception as e:
            logger.error(f"Error sending complete registration to admin: {e}")
                
    except Exception as e:
        logger.error(f"Error in send_complete_registration_to_admin: {e}")

async def complete_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Complete registration and send all data to admin"""
    try:
        if update.message.contact:
            phone_number = update.message.contact.phone_number
            context.user_data['phone'] = phone_number
            
            # ذخیره اطلاعات کاربر
            user_data = context.user_data
            user_id = update.effective_user.id
            
            # ارسال اطلاعات کامل به ادمین
            await send_complete_registration_to_admin(update, context)
            
            await update.message.reply_text(
                "✅ اطلاعات شما با موفقیت ثبت شد.\n\nدر حال حاضر در انتظار تایید ادمین هستید. پس از تایید، دسترسی کامل به ربات خواهید داشت.",
                reply_markup=ReplyKeyboardRemove()
            )
            
            # بازگشت به حالت اولیه
            return ConversationHandler.END
            
        else:
            await update.message.reply_text(
                "لطفا از دکمه اشتراک تلفن استفاده کنید:",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("📞 اشتراک تلفن", request_contact=True)]],
                    resize_keyboard=True,
                    one_time_keyboard=True
                )
            )
            return States.REGISTER_PHONE
            
    except Exception as e:
        logger.error(f"Error in complete_registration: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return States.REGISTER_PHONE




# Admin Commands
async def upload_excel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start Excel upload process for admin"""
    try:
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Check if user is admin
                cursor.execute('''
                SELECT is_admin FROM users WHERE id = %s
                ''', (update.effective_user.id,))
                result = cursor.fetchone()
                
                if not result or not result[0]:
                    await update.message.reply_text("شما مجوز انجام این کار را ندارید.")
                    return
    
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
            await update.message.reply_text("خطا در بررسی مجوزها.")
            return
        finally:
            if conn:
                conn.close()
        
        await update.message.reply_text(
            "لطفا فایل اکسل جدید را ارسال کنید یا لینک گیتهاب را وارد نمایید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.ADMIN_UPLOAD_EXCEL
    except Exception as e:
        logger.error(f"Error in upload_excel_start: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def handle_excel_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Excel file upload with merging functionality"""
    try:
        if update.message.document:
            # Handle document upload
            file = await context.bot.get_file(update.message.document.file_id)
            file_path = await download_file(file, "drug_prices", "admin")
            
            try:
                # Process new Excel file
                new_df = pd.read_excel(file_path, engine='openpyxl')
                
                # Rename columns to standard names
                column_mapping = {
                    'نام فارسی': 'name',
                    'قیمت واحد': 'price',
                    'name': 'name',  # For backward compatibility
                    'price': 'price'  # For backward compatibility
                }
                new_df = new_df.rename(columns=column_mapping)
                
                # Clean and prepare new data
                new_df = new_df[['name', 'price']].dropna()
                new_df['name'] = new_df['name'].astype(str).str.strip()
                new_df['price'] = new_df['price'].astype(str).str.strip()
                new_df = new_df.drop_duplicates()
                
                # Load existing data if available
                try:
                    existing_df = pd.read_excel(excel_file, engine='openpyxl')
                    existing_df = existing_df[['name', 'price']].dropna()
                    existing_df['name'] = existing_df['name'].astype(str).str.strip()
                    existing_df['price'] = existing_df['price'].astype(str).str.strip()
                except:
                    existing_df = pd.DataFrame(columns=['name', 'price'])
                
                # Merge data - keep higher price for duplicates
                merged_df = pd.concat([existing_df, new_df])
                merged_df['price'] = merged_df['price'].apply(parse_price)
                merged_df = merged_df.sort_values('price', ascending=False)
                merged_df = merged_df.drop_duplicates('name', keep='first')
                merged_df = merged_df.sort_values('name')
                
                # Save merged data
                merged_df.to_excel(excel_file, index=False, engine='openpyxl')
                
                # Prepare statistics
                added_count = len(new_df)
                total_count = len(merged_df)
                duplicates_count = len(new_df) + len(existing_df) - len(merged_df)
                
                await update.message.reply_text(
                    f"✅ فایل اکسل با موفقیت ادغام شد!\n\n"
                    f"آمار:\n"
                    f"- داروهای جدید اضافه شده: {added_count}\n"
                    f"- موارد تکراری: {duplicates_count}\n"
                    f"- کل داروها پس از ادغام: {total_count}\n\n"
                    f"برای استفاده از داده‌های جدید، ربات را ریستارت کنید."
                )
                
                # Save to database
                conn = None
                try:
                    conn = get_db_connection()
                    with conn.cursor() as cursor:
                        cursor.execute('''
                        INSERT INTO admin_settings (excel_url, last_updated)
                        VALUES (%s, CURRENT_TIMESTAMP)
                        ON CONFLICT (id) DO UPDATE SET
                            excel_url = EXCLUDED.excel_url,
                            last_updated = EXCLUDED.last_updated
                        ''', (file_path,))
                        conn.commit()
                except Exception as e:
                    logger.error(f"Error saving excel info: {e}")
                finally:
                    if conn:
                        conn.close()
                    
            except Exception as e:
                logger.error(f"Error processing excel file: {e}")
                await update.message.reply_text(
                    "❌ خطا در پردازش فایل اکسل. لطفا مطمئن شوید:\n"
                    "1. فایل دارای ستون‌های 'نام فارسی' و 'قیمت واحد' است\n"
                    "2. فرمت فایل صحیح است (xlsx یا xls)"
                )
                
        elif update.message.text and update.message.text.startswith('http'):
            # Handle URL (similar logic as above can be implemented)
            await update.message.reply_text("در حال حاضر آپلود از لینک برای این ورژن غیرفعال است")
        else:
            await update.message.reply_text(
                "لطفا یک فایل اکسل با ستون‌های 'نام فارسی' و 'قیمت واحد' ارسال کنید"
            )
            return States.ADMIN_UPLOAD_EXCEL
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in handle_excel_upload: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END



async def verify_pharmacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify a pharmacy (admin only)"""
    try:
        if not update.message.text.startswith('/verify_'):
            return
        
        try:
            pharmacy_id = int(update.message.text.split('_')[1])
        except (IndexError, ValueError):
            await update.message.reply_text("فرمت دستور نادرست است. از /verify_12345 استفاده کنید.")
            return
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Verify the pharmacy
                cursor.execute('''
                UPDATE pharmacies 
                SET verified = TRUE, 
                    verified_at = CURRENT_TIMESTAMP,
                    admin_id = %s
                WHERE user_id = %s
                RETURNING name
                ''', (update.effective_user.id, pharmacy_id))
                
                result = cursor.fetchone()
                if not result:
                    await update.message.reply_text("داروخانه با این شناسه یافت نشد.")
                    return
                
                # Generate an admin code for the pharmacy
                admin_code = str(random.randint(10000, 99999))
                cursor.execute('''
                UPDATE pharmacies 
                SET admin_code = %s
                WHERE user_id = %s
                ''', (admin_code, pharmacy_id))
                
                # Mark user as verified
                cursor.execute('''
                UPDATE users 
                SET is_verified = TRUE 
                WHERE id = %s
                ''', (pharmacy_id,))
                
                conn.commit()
                
                await update.message.reply_text(
                    f"✅ داروخانه {result[0]} با موفقیت تایید شد!\n\n"
                    f"کد ادمین برای این داروخانه: {admin_code}\n"
                    "این کد را می‌توانید به داروخانه بدهید تا دیگران با آن ثبت نام کنند."
                )
                
                # Notify pharmacy
                try:
                    await context.bot.send_message(
                        chat_id=pharmacy_id,
                        text=f"✅ داروخانه شما توسط ادمین تایید شد!\n\n"
                             f"شما اکنون می‌توانید از تمام امکانات ربات استفاده کنید."
                    )
                except Exception as e:
                    logger.error(f"Failed to notify pharmacy: {e}")
                    
        except Exception as e:
            logger.error(f"Error verifying pharmacy: {e}")
            await update.message.reply_text("خطا در تایید داروخانه.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in verify_pharmacy: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
async def toggle_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle medical category selection with instant visual feedback"""
    await clear_conversation_state(update, context, silent=True)
    query = update.callback_query
    await query.answer("🔄 در حال به‌روزرسانی...")  # بازخورد فوری
    
    if not query.data or not query.data.startswith("togglecat_"):
        return
    
    conn = None
    try:
        category_id = int(query.data.split("_")[1])
        user_id = query.from_user.id
        
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Toggle category status
            cursor.execute('''
            WITH toggled AS (
                DELETE FROM user_categories 
                WHERE user_id = %s AND category_id = %s
                RETURNING 1
            )
            INSERT INTO user_categories (user_id, category_id)
            SELECT %s, %s
            WHERE NOT EXISTS (SELECT 1 FROM toggled)
            ''', (user_id, category_id, user_id, category_id))
            conn.commit()
            
            # Get updated categories
            with conn.cursor(cursor_factory=extras.DictCursor) as dict_cursor:
                dict_cursor.execute('''
                SELECT mc.id, mc.name, 
                       EXISTS(SELECT 1 FROM user_categories uc 
                              WHERE uc.user_id = %s AND uc.category_id = mc.id) as selected
                FROM medical_categories mc
                ORDER BY mc.name
                ''', (user_id,))
                categories = dict_cursor.fetchall()
                
                # Build new keyboard with better visual feedback
                keyboard = []
                row = []
                for cat in categories:
                    # Use more distinct emojis
                    emoji = "🌟 " if cat['selected'] else "⚪ "
                    button = InlineKeyboardButton(
                        f"{emoji}{cat['name']}",
                        callback_data=f"togglecat_{cat['id']}"
                    )
                    row.append(button)
                    if len(row) == 2:
                        keyboard.append(row)
                        row = []
                
                if row:
                    keyboard.append(row)
                
                # Add save button with better emoji
                keyboard.append([InlineKeyboardButton("💾 ذخیره تغییرات", callback_data="save_categories")])
                
                # Faster edit with less waiting time
                try:
                    await query.edit_message_reply_markup(
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception as e:
                    if "Message is not modified" in str(e):
                        # No change needed
                        await query.answer("✅")
                    else:
                        logger.error(f"Error updating message: {e}")
                        await query.answer("⚠️ خطا در بروزرسانی", show_alert=True)
                    
    except Exception as e:
        logger.error(f"Error in toggle_category: {e}")
        await query.answer("⚠️ خطا در پردازش", show_alert=True)
    finally:
        if conn:
            conn.close()

async def save_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save selected medical categories"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "✅ شاخه‌های دارویی شما با موفقیت به‌روزرسانی شد.",
            reply_markup=None
        )
        
        # Return to main menu
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['تنظیم شاخه‌های دارویی', 'لیست داروهای من'],
            ['ثبت نیاز جدید', 'لیست نیازهای من']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="به منوی اصلی بازگشتید. لطفا یک گزینه را انتخاب کنید:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error in save_categories: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")


async def setup_medical_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initialize category selection screen"""
    await clear_conversation_state(update, context, silent=True)
    conn = None
    try:
        user_id = update.effective_user.id
        conn = get_db_connection()
        with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
            cursor.execute('''
            SELECT mc.id, mc.name, 
                   EXISTS(SELECT 1 FROM user_categories uc 
                          WHERE uc.user_id = %s AND uc.category_id = mc.id) as selected
            FROM medical_categories mc
            ORDER BY mc.name
            ''', (user_id,))
            categories = cursor.fetchall()
            
            if not categories:
                await (update.callback_query.edit_message_text if update.callback_query 
                      else update.message.reply_text)("هیچ شاخه دارویی تعریف نشده است.")
                return
            
            # Build 2-column keyboard
            keyboard = []
            row = []
            for cat in categories:
                emoji = "✅ " if cat['selected'] else "◻️ "
                button = InlineKeyboardButton(
                    f"{emoji}{cat['name']}",
                    callback_data=f"togglecat_{cat['id']}"
                )
                row.append(button)
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            
            if row:
                keyboard.append(row)
            
            keyboard.append([InlineKeyboardButton("💾 ذخیره", callback_data="save_categories")])
            
            text = "لطفا شاخه‌های دارویی مورد نظر خود را انتخاب کنید:"
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.message.reply_text(
                    text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard))
            
            return States.SETUP_CATEGORIES
            
    except Exception as e:
        logger.error(f"Error in setup_medical_categories: {e}")
        await (update.callback_query.answer if update.callback_query 
              else update.message.reply_text)("خطا در دریافت لیست شاخه‌ها")
    finally:
        if conn:
            conn.close()
# Drug Management
async def handle_add_drug_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle add drug from inline query result"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data.startswith("add_drug_"):
            idx = int(query.data.split("_")[2])
            if 0 <= idx < len(drug_list):
                selected_drug = drug_list[idx]
                context.user_data['selected_drug'] = {
                    'name': selected_drug[0],
                    'price': selected_drug[1]
                }
                
                await query.edit_message_text(
                    f"✅ دارو انتخاب شده: {selected_drug[0]}\n💰 قیمت: {selected_drug[1]}\n\n"
                    "📅 لطفا تاریخ انقضا را وارد کنید (مثال: 2026/01/23):",
                    reply_markup=None
                )
                return States.ADD_DRUG_DATE
                
    except Exception as e:
        logger.error(f"Error handling add drug callback: {e}")
        await query.edit_message_text("خطا در انتخاب دارو. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def handle_need_drug_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback for need drug selection from inline query (now asks for quantity directly)"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data.startswith("need_drug_"):
            idx = int(query.data.split("_")[2])
            if 0 <= idx < len(drug_list):
                selected_drug = drug_list[idx]
                # Store selected drug for the need
                context.user_data['selected_drug_for_need'] = {
                    'name': selected_drug[0],
                    'price': selected_drug[1]
                }
                # Also set need_name so we don't require a separate description step
                context.user_data['need_name'] = selected_drug[0]
                
                await query.edit_message_text(
                    f"✅ داروی مورد نیاز انتخاب شد: {selected_drug[0]}\n💰 قیمت مرجع: {selected_drug[1]}\n\n"
                    "📦 لطفا تعداد مورد نیاز را وارد کنید:",
                    reply_markup=None
                )
                return States.ADD_NEED_QUANTITY
                
    except Exception as e:
        logger.error(f"Error handling need drug callback: {e}")
        await query.edit_message_text("خطا در انتخاب دارو. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def add_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start process to add a drug item with inline query"""
    await clear_conversation_state(update, context, silent=True)
    try:
        await ensure_user(update, context)
        
        # 🔥 تنظیم state برای تشخیص در اینلاین کوئری
        context.user_data['_conversation_state'] = States.SEARCH_DRUG_FOR_ADDING
        
        # ایجاد دکمه برای جستجوی اینلاین برای اضافه کردن دارو
        keyboard = [
            [InlineKeyboardButton(
                "🔍 جستجوی دارو برای اضافه کردن", 
                switch_inline_query_current_chat="add "
            )]
            
        ]
        
        await update.message.reply_text(
            "برای اضافه کردن دارو جدید، روی دکمه جستجو کلیک کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.SEARCH_DRUG_FOR_ADDING
    except Exception as e:
        logger.error(f"Error in add_drug_item: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

def split_drug_info(full_text):
    """جدا کردن نام دارو (قسمت غیرعددی) و اطلاعات عددی/توضیحات"""
    # پیدا کردن اولین عدد در متن
    match = re.search(r'\d', full_text)
    if match:
        split_pos = match.start()
        title = full_text[:split_pos].strip()
        description = full_text[split_pos:].strip()
    else:
        title = full_text
        description = "قیمت نامشخص"
    return title, description
async def handle_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline query for drug search with separate options for add and need"""
    await clear_conversation_state(update, context, silent=True)
    query = update.inline_query.query
    
    # 🔥 تشخیص نوع جستجو از context - بهبود یافته
    current_state = context.user_data.get('_conversation_state')
    
    # تشخیص بر اساس state و query
    if query.startswith("need ") or current_state == States.SEARCH_DRUG_FOR_NEED:
        search_type = "need"
        query = query[5:].strip() if query.startswith("need ") else query
    elif query.startswith("add ") or current_state == States.SEARCH_DRUG_FOR_ADDING:
        search_type = "add"
        query = query[4:].strip() if query.startswith("add ") else query
    else:
        search_type = "search"  # پیش‌فرض
    
    if not query:
        query = ""
    
    results = []
    for idx, (name, price) in enumerate(drug_list):
        if query.lower() in name.lower():
            title_part = name.split()[0] if name.split() else name
            desc_part = ' '.join(name.split()[1:]) if len(name.split()) > 1 else name
            
            if search_type == "add":
                results.append(
                    InlineQueryResultArticle(
                        id=f"add_{idx}",
                        title=f"➕ {title_part}",
                        description=f"{desc_part} - قیمت: {price}",
                        input_message_content=InputTextMessageContent(
                            f"💊 {name}\n💰 قیمت: {price}"
                        ),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                "➕ اضافه به لیست داروها",
                                callback_data=f"add_drug_{idx}"
                            )]
                        ])
                    )
                )
            elif search_type == "need":
                results.append(
                    InlineQueryResultArticle(
                        id=f"need_{idx}",
                        title=f"📋 {title_part}",
                        description=f"{desc_part} - قیمت: {price}",
                        input_message_content=InputTextMessageContent(
                            f"💊 {name}\n💰 قیمت: {price}"
                        ),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                "📋 ثبت نیاز",
                                callback_data=f"need_drug_{idx}"
                            )]
                        ])
                    )
                )
            else:
                results.append(
                    InlineQueryResultArticle(
                        id=f"search_{idx}",
                        title=f"🔍 {title_part}",
                        description=f"{desc_part} - قیمت: {price}",
                        input_message_content=InputTextMessageContent(
                            f"💊 {name}\n💰 قیمت: {price}"
                        ),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                "🏥 مشاهده داروخانه‌ها",
                                callback_data=f"search_drug_{idx}"
                            )]
                        ])
                    )
                )
            
        if len(results) >= 50:
            break
    
    await update.inline_query.answer(results)
async def handle_chosen_inline_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        result_id = update.chosen_inline_result.result_id
        user_id = update.chosen_inline_result.from_user.id

        if result_id.startswith('add_'):
            # پردازش برای اضافه کردن دارو
            idx = int(result_id.split('_')[1])
            drug_name, drug_price = drug_list[idx]

            context.user_data['selected_drug'] = {
                'name': drug_name.strip(),
                'price': drug_price.strip()
            }

            # state را به ADD_DRUG_FROM_INLINE تغییر دهید
            context.user_data['_conversation_state'] = States.ADD_DRUG_FROM_INLINE

            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ دارو انتخاب شده: {drug_name}\n💰 قیمت: {drug_price}\n\n📅 لطفا تاریخ انقضا را وارد کنید (مثال: 2026/01/23):"
            )
            return States.ADD_DRUG_DATE  # به state تاریخ بروید

        elif result_id.startswith('need_'):
            # پردازش برای ثبت نیاز
            idx = int(result_id.split('_')[1])
            drug_name, drug_price = drug_list[idx]

            context.user_data['need_name'] = drug_name.strip()
            context.user_data['selected_drug_for_need'] = {
                'name': drug_name.strip(),
                'price': drug_price.strip()
            }

            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ داروی مورد نیاز انتخاب شد: {drug_name}\n💰 قیمت مرجع: {drug_price}\n\n📦 لطفا تعداد مورد نیاز را وارد کنید:"
            )
            return States.ADD_NEED_QUANTITY

    except Exception as e:
        logger.error(f"Error in handle_chosen_inline_result: {e}", exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=update.chosen_inline_result.from_user.id,
                text="خطایی در انتخاب دارو رخ داد. لطفا دوباره تلاش کنید."
            )
        except Exception:
            pass
        return ConversationHandler.END
async def search_drug_for_adding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع جستجو با اینلاین کوئری"""
    await clear_conversation_state(update, context, silent=True)
    keyboard = [
        [InlineKeyboardButton("🔍 جستجوی دارو", switch_inline_query_current_chat="")]
        
    ]
    
    await update.message.reply_text(
        "برای اضافه کردن دارو جدید، روی دکمه جستجو کلیک کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return States.SEARCH_DRUG_FOR_ADDING


async def select_drug_for_adding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Select drug from search results to add"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()

        if query.data == "cancel":
            await cancel(update, context)
            return ConversationHandler.END
        
        if query.data == "back":
            await query.edit_message_text("لطفا نام دارویی که می‌خواهید اضافه کنید را جستجو کنید:")
            return States.SEARCH_DRUG_FOR_ADDING
        
        if not query.data.startswith("select_drug_"):
            await query.edit_message_text("خطا در انتخاب دارو. لطفا دوباره تلاش کنید.")
            return States.SEARCH_DRUG_FOR_ADDING
        
        try:
            selected_idx = int(query.data.replace("select_drug_", ""))
            matched_drugs = context.user_data.get('matched_drugs', [])
            
            if selected_idx < 0 or selected_idx >= len(matched_drugs):
                await query.edit_message_text("خطا: داروی انتخاب شده معتبر نیست.")
                return States.SEARCH_DRUG_FOR_ADDING
                
            selected_drug = matched_drugs[selected_idx]
            
            context.user_data['selected_drug'] = {
                'name': selected_drug[0],
                'price': selected_drug[1]
            }
            
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_search")]
            ]
            
            await query.edit_message_text(
                f"✅ دارو انتخاب شده: {selected_drug[0]}\n"
                f"💰 قیمت: {selected_drug[1]}\n\n"
                "📅 لطفا تاریخ انقضا را وارد کنید (مثال: 1403/05/15):",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return States.ADD_DRUG_DATE
        
        except Exception as e:
            logger.error(f"Error in select_drug_for_adding: {e}")
            await query.edit_message_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
            return States.SEARCH_DRUG_FOR_ADDING
    except Exception as e:
        logger.error(f"Error in select_drug_for_adding: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END



async def add_drug_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message and update.message.text:
            expiry_date = update.message.text.strip()
            logger.info(f"User {update.effective_user.id} entered expiry date: {expiry_date}")
            
            # تبدیل اعداد فارسی به انگلیسی
            persian_to_english = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
            expiry_date = expiry_date.translate(persian_to_english)
            
            # Validate date format
            if not re.match(r'^\d{4}/\d{2}/\d{2}$', expiry_date):
                await update.message.reply_text(
                    "فرمت تاریخ نامعتبر است. لطفا تاریخ را به فرمت 2026/01/23 وارد کنید:"
                )
                return States.ADD_DRUG_DATE
            
            context.user_data['expiry_date'] = expiry_date
            logger.info(f"Stored expiry_date: {expiry_date} for user {update.effective_user.id}")
            
            await update.message.reply_text("📦 لطفا تعداد موجودی را وارد کنید:")
            return States.ADD_DRUG_QUANTITY  # این خط مهم است
            
        elif update.callback_query:
            query = update.callback_query
            await query.answer()
            if query.data == "back_to_search":
                return await search_drug_for_adding(update, context)
            
            await query.edit_message_text("لطفا تاریخ انقضا را به صورت متنی وارد کنید (مثال: 2026/01/23):")
            return States.ADD_DRUG_DATE
            
        else:
            logger.warning(f"Unexpected update type for user {update.effective_user.id}: {update}")
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="لطفا تاریخ انقضا را به فرمت 2026/01/23 وارد کنید:"
            )
            return States.ADD_DRUG_DATE
            
    except Exception as e:
        logger.error(f"Error in add_drug_date for user {update.effective_user.id}: {e}")
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="خطایی رخ داده است. لطفا دوباره تاریخ انقضا را وارد کنید:"
        )
        return States.ADD_DRUG_DATE

async def add_drug_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت تعداد برای داروی انتخاب شده"""
    await clear_conversation_state(update, context, silent=True)
    try:
        quantity = update.message.text.strip()
        
        try:
            quantity = int(quantity)
            if quantity <= 0:
                await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید.")
                return States.ADD_DRUG_QUANTITY
        except ValueError:
            await update.message.reply_text("لطفا یک عدد صحیح وارد کنید.")
            return States.ADD_DRUG_QUANTITY
        
        context.user_data['drug_quantity'] = quantity
        
        # ذخیره اطلاعات در دیتابیس
        return await save_drug_item(update, context)
        
    except Exception as e:
        logger.error(f"Error in add_drug_quantity: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
async def save_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره دارو بعد از وارد کردن تعداد"""
    try:
        # Get all required data from context
        selected_drug = context.user_data.get('selected_drug', {})
        expiry_date = context.user_data.get('expiry_date')
        quantity_text = update.message.text.strip()

        # Validate all required fields
        if not selected_drug or not expiry_date:
            await update.message.reply_text(
                "❌ اطلاعات دارو ناقص است. لطفا دوباره از ابتدا شروع کنید.",
                reply_markup=ReplyKeyboardRemove()
            )
            return await clear_conversation_state(update, context)

        # Validate quantity - تبدیل اعداد فارسی به انگلیسی
        try:
            persian_to_english = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
            quantity_text = quantity_text.translate(persian_to_english)
            
            # استخراج فقط ارقام
            digits = ''.join(filter(str.isdigit, quantity_text))
            if not digits:
                await update.message.reply_text("❌ لطفا یک عدد معتبر وارد کنید:")
                return States.ADD_DRUG_QUANTITY
                
            quantity = int(digits)
            if quantity <= 0:
                await update.message.reply_text("❌ لطفا عددی بزرگتر از صفر وارد کنید:")
                return States.ADD_DRUG_QUANTITY
        except ValueError:
            await update.message.reply_text("❌ لطفا یک عدد صحیح وارد کنید:")
            return States.ADD_DRUG_QUANTITY

        # Save to database - با بررسی خطاهای دقیق‌تر
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # ابتدا بررسی کنیم آیا دارو قبلاً وجود دارد
                cursor.execute('''
                SELECT id FROM drug_items 
                WHERE user_id = %s AND name = %s AND date = %s
                ''', (update.effective_user.id, selected_drug['name'], expiry_date))
                
                existing_drug = cursor.fetchone()
                
                if existing_drug:
                    # اگر دارو وجود دارد، تعداد را آپدیت کنیم
                    cursor.execute('''
                    UPDATE drug_items SET quantity = quantity + %s
                    WHERE id = %s
                    ''', (quantity, existing_drug[0]))
                    action = "آپدیت"
                else:
                    # اگر دارو جدید است، insert کنیم
                    cursor.execute('''
                    INSERT INTO drug_items (user_id, name, price, date, quantity)
                    VALUES (%s, %s, %s, %s, %s)
                    ''', (
                        update.effective_user.id,
                        selected_drug['name'],
                        selected_drug['price'],
                        expiry_date,
                        quantity
                    ))
                    action = "ثبت"
                
                conn.commit()
                
                # پیام موفقیت
                success_msg = (
                    f"✅ دارو با موفقیت {action} شد:\n"
                    f"💊 نام: {selected_drug['name']}\n"
                    f"💰 قیمت: {selected_drug['price']}\n"
                    f"📅 تاریخ انقضا: {expiry_date}\n"
                    f"📦 تعداد: {quantity}"
                )
                await update.message.reply_text(success_msg)
                
        except Exception as e:
            logger.error(f"Error saving drug item: {str(e)}")
            if conn:
                conn.rollback()
            
            # پیام خطای دقیق‌تر
            error_msg = "❌ خطا در ثبت دارو. "
            if "duplicate key" in str(e).lower():
                error_msg += "این دارو قبلاً ثبت شده است."
            else:
                error_msg += "لطفا دوباره تلاش کنید."
            
            await update.message.reply_text(error_msg)
            
        finally:
            if conn:
                conn.close()
                
        # پاک‌سازی context
        for key in ['selected_drug', 'expiry_date', 'drug_quantity', '_conversation_state']:
            context.user_data.pop(key, None)
        
        # بازگشت به منوی اصلی
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "به منوی اصلی بازگشتید:",
            reply_markup=reply_markup
        )
        
        return ConversationHandler.END
                
    except Exception as e:
        logger.error(f"Error in save_drug_item: {str(e)}")
        await update.message.reply_text("❌ خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        
        # بازگشت به منوی اصلی در صورت خطا
        return await clear_conversation_state(update, context)
async def list_my_drugs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست داروهای کاربر با فقط دو دکمه: ویرایش داروها و بازگشت"""
    try:
        # پاک کردن stateهای قبلی
        await clear_conversation_state(update, context, silent=True)
        
        await ensure_user(update, context)
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT id, name, price, date, quantity 
                FROM drug_items 
                WHERE user_id = %s AND quantity > 0
                ORDER BY name
                ''', (update.effective_user.id,))
                drugs = cursor.fetchall()
                
                if drugs:
                    message = "💊 لیست داروهای شما:\n\n"
                    for i, drug in enumerate(drugs, 1):
                        message += (
                            f"{i}. {drug['name']}\n"
                            f"   قیمت: {drug['price']}\n"
                            f"   تاریخ انقضا: {drug['date']}\n"
                            f"   موجودی: {drug['quantity']}\n\n"
                        )
                    
                    # ذخیره لیست داروها در context برای استفاده در ویرایش
                    context.user_data['user_drugs_list'] = drugs
                    
                    # ساخت کیبورد ساده با فقط دو دکمه
                    keyboard = [
                        ['✏️ ویرایش داروها'],
                        ['🔙 بازگشت به منوی اصلی']
                    ]
                    
                    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                    
                    await update.message.reply_text(
                        message,
                        reply_markup=reply_markup
                    )
                    
                    return States.EDIT_DRUG
                else:
                    await update.message.reply_text("شما هنوز هیچ دارویی اضافه نکرده‌اید.")
                    
        except Exception as e:
            logger.error(f"Error listing drugs: {e}")
            await update.message.reply_text("خطا در دریافت لیست داروها.")
        finally:
            if conn:
                conn.close()
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in list_my_drugs: {e}")
        return ConversationHandler.END
async def edit_drugs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع فرآیند ویرایش داروها - نمایش لیست داروها با دکمه‌های ✏️"""
    try:
        # حذف stateهای مربوط به نیازها
        need_keys = ['editing_need', 'edit_field', 'user_needs_list', 'editing_needs_list']
        for key in need_keys:
            context.user_data.pop(key, None)
        
        # استفاده از داروهای ذخیره شده در context یا دریافت از دیتابیس
        drugs = context.user_data.get('user_drugs_list', [])
        
        if not drugs:
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                    cursor.execute('''
                    SELECT id, name, price, date, quantity 
                    FROM drug_items 
                    WHERE user_id = %s AND quantity > 0
                    ORDER BY name
                    ''', (update.effective_user.id,))
                    drugs = cursor.fetchall()
                    
            except Exception as e:
                logger.error(f"Error in edit_drugs: {e}", exc_info=True)
                await update.message.reply_text("خطا در دریافت لیست داروها.")
                return ConversationHandler.END
            finally:
                if conn:
                    conn.close()

        if not drugs:
            await update.message.reply_text("هیچ دارویی برای ویرایش وجود ندارد.")
            return ConversationHandler.END
        
        # ساخت کیبورد برای انتخاب دارو - هر دارو با دکمه ✏️
        keyboard = []
        for drug in drugs:
            # نمایش نام کامل با دکمه ✏️
            display_name = drug['name']
            button_text = f"✏️ {display_name.strip()}"
            keyboard.append([button_text])
        
        # دکمه بازگشت به لیست داروها (نه منوی اصلی)
        keyboard.append(["🔙 بازگشت به لیست داروها"])
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "لطفا دارویی که می‌خواهید ویرایش کنید را انتخاب کنید:",
            reply_markup=reply_markup
        )
        
        # ذخیره داروها در context برای استفاده در مرحله بعد
        context.user_data['editing_drugs_list'] = drugs
        
        return States.EDIT_DRUG
                
    except Exception as e:
        logger.error(f"Error in edit_drugs: {e}", exc_info=True)
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END


async def handle_select_drug_for_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت انتخاب دارو خاص برای ویرایش"""
    try:
        if not update.message:
            return States.EDIT_DRUG
            
        selection = update.message.text
        
        # اولویت اول: بررسی دکمه‌های بازگشت
        if selection in ["🔙 بازگشت", "🔙 بازگشت به لیست داروها", "🔙 بازگشت به منوی اصلی"]:
            return await list_my_drugs(update, context)
            
        # سپس: بررسی دکمه‌های عملیاتی
        if selection in ["✏️ ویرایش تاریخ", "✏️ ویرایش تعداد", "🗑️ حذف دارو"]:
            return await handle_drug_edit_action_from_keyboard(update, context)
            
        if selection in ["✅ بله، حذف شود", "❌ خیر، انصراف"]:
            return await handle_drug_deletion_confirmation(update, context)
        
        # 🔥 مهم: بررسی اینکه آیا کاربر دکمه "ویرایش داروها" را زده
        if selection == "✏️ ویرایش داروها":
            # این دکمه عملیاتی است، نه نام دارو - پس لیست داروها را نمایش بده
            return await edit_drugs(update, context)
        
        # سپس بررسی انتخاب دارو از لیست
        if selection.startswith("✏️ "):
            # استخراج نام کامل دارو از دکمه
            drug_name = selection[2:].strip()
            
            # دریافت لیست داروها
            drugs = context.user_data.get('editing_drugs_list', [])
            if not drugs:
                drugs = context.user_data.get('user_drugs_list', [])
            
            # اگر هنوز لیست داروها موجود نیست، از دیتابیس بگیر
            if not drugs:
                conn = None
                try:
                    conn = get_db_connection()
                    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                        cursor.execute('''
                        SELECT id, name, price, date, quantity 
                        FROM drug_items 
                        WHERE user_id = %s AND quantity > 0
                        ORDER BY name
                        ''', (update.effective_user.id,))
                        drugs = cursor.fetchall()
                        context.user_data['editing_drugs_list'] = drugs
                except Exception as e:
                    logger.error(f"Error fetching drugs from DB: {e}")
                finally:
                    if conn:
                        conn.close()
            
            # پیدا کردن داروی انتخاب شده
            selected_drug = None
            for drug in drugs:
                if drug['name'].strip() == drug_name:
                    selected_drug = drug
                    break
            
            if selected_drug:
                context.user_data['editing_drug'] = dict(selected_drug)
                
                keyboard = [
                    ['✏️ ویرایش تاریخ'],
                    ['✏️ ویرایش تعداد'],
                    ['🗑️ حذف دارو'],
                    ['🔙 بازگشت به لیست داروها']
                ]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                
                await update.message.reply_text(
                    f"ویرایش دارو:\n\n"
                    f"💊 نام: {selected_drug['name']}\n"
                    f"💰 قیمت: {selected_drug['price']}\n"
                    f"📅 تاریخ انقضا: {selected_drug['date']}\n"
                    f"📦 تعداد: {selected_drug['quantity']}\n\n"
                    "لطفا گزینه مورد نظر را انتخاب کنید:",
                    reply_markup=reply_markup
                )
                return States.EDIT_DRUG
            else:
                # 🔥 این پیام خطا حذف شده - فقط لیست داروها را دوباره نمایش بده
                return await edit_drugs(update, context)
        
        # 🔥 اگر هیچکدام از موارد بالا نبود، احتمالاً کاربر عدد وارد کرده
        # اما ما در این state نباید عدد دریافت کنیم، پس خطا بده
        await update.message.reply_text(
            "❌ لطفا یکی از گزینه‌های موجود را انتخاب کنید.",
            reply_markup=ReplyKeyboardMarkup([
                ['✏️ ویرایش تاریخ'],
                ['✏️ ویرایش تعداد'],
                ['🗑️ حذف دارو'],
                ['🔙 بازگشت به لیست داروها']
            ], resize_keyboard=True)
        )
        return States.EDIT_DRUG
        
    except Exception as e:
        logger.error(f"Error in handle_select_drug_for_edit: {e}", exc_info=True)
        try:
            if update.message:
                await update.message.reply_text("خطا در انتخاب دارو.")
        except:
            pass
        return States.EDIT_DRUG
async def handle_drug_edit_action_from_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drug edit actions from keyboard buttons - ویرایش تاریخ و تعداد و حذف"""
    try:
        if not update.message:
            logger.error("No message in handle_drug_edit_action_from_keyboard")
            return States.EDIT_DRUG
            
        action = update.message.text
        drug = context.user_data.get('editing_drug')
        
        if not drug:
            await update.message.reply_text("❌ ابتدا یک دارو را برای ویرایش انتخاب کنید.")
            return await edit_drugs(update, context)
        
        if action == "✏️ ویرایش تاریخ":
            await update.message.reply_text(
                f"📅 تاریخ انقضای فعلی: {drug['date']}\n\nلطفا تاریخ جدید را وارد کنید (مثال: 2026/01/23):",
                reply_markup=ReplyKeyboardRemove()
            )
            context.user_data['edit_field'] = 'date'
            return States.EDIT_DRUG
            
        elif action == "✏️ ویرایش تعداد":
            await update.message.reply_text(
                f"📦 تعداد فعلی: {drug['quantity']}\n\nلطفا تعداد جدید را وارد کنید:",
                reply_markup=ReplyKeyboardRemove()
            )
            context.user_data['edit_field'] = 'quantity'
            return States.EDIT_DRUG
            
        elif action == "🗑️ حذف دارو":
            keyboard = [
                ['✅ بله، حذف شود'],
                ['❌ خیر، انصراف']
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"⚠️ آیا مطمئن هستید که می‌خواهید داروی «{drug['name']}» را حذف کنید؟",
                reply_markup=reply_markup
            )
            return States.EDIT_DRUG
            
    except Exception as e:
        logger.error(f"Error in handle_drug_edit_action_from_keyboard: {e}")
        await update.message.reply_text("❌ خطا در پردازش درخواست.")
        return States.EDIT_DRUG
async def handle_drug_deletion_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drug deletion confirmation from keyboard"""
    try:
        if not update.message:
            return States.EDIT_DRUG
            
        confirmation = update.message.text
        drug = context.user_data.get('editing_drug')
        
        if not drug:
            await update.message.reply_text("❌ اطلاعات دارو یافت نشد.")
            return await clear_conversation_state(update, context)
        
        if confirmation == "✅ بله، حذف شود":
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor() as cursor:
                    # حذف دارو
                    cursor.execute(
                        'DELETE FROM drug_items WHERE id = %s AND user_id = %s',
                        (drug['id'], update.effective_user.id)
                    )
                    deleted_rows = cursor.rowcount
                    conn.commit()
                    
                    if deleted_rows > 0:
                        # پاک‌سازی کامل و بازگشت به منوی اصلی
                        context.user_data.clear()
                        
                        keyboard = [
                            ['اضافه کردن دارو', 'جستجوی دارو'],
                            ['لیست داروهای من', 'ثبت نیاز جدید'],
                            ['لیست نیازهای من', 'ساخت کد پرسنل'],
                            ['تنظیم شاخه‌های دارویی']
                        ]
                        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                        
                        await update.message.reply_text(
                            f"✅ داروی «{drug['name']}» با موفقیت حذف شد.\n\nبه منوی اصلی بازگشتید:",
                            reply_markup=reply_markup
                        )
                        return ConversationHandler.END
                    else:
                        await update.message.reply_text(
                            "❌ دارو یافت نشد یا قبلاً حذف شده است.",
                            reply_markup=ReplyKeyboardRemove()
                        )
                        return await clear_conversation_state(update, context)
                    
            except Exception as e:
                logger.error(f"Error deleting drug {drug['id']}: {e}")
                if conn:
                    conn.rollback()
                
                # پاک‌سازی و بازگشت به منوی اصلی در صورت خطا
                context.user_data.clear()
                
                keyboard = [
                    ['اضافه کردن دارو', 'جستجوی دارو'],
                    ['لیست داروهای من', 'ثبت نیاز جدید'],
                    ['لیست نیازهای من', 'ساخت کد پرسنل'],
                    ['تنظیم شاخه‌های دارویی']
                ]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                
                await update.message.reply_text(
                    "❌ خطا در حذف دارو.\n\nبه منوی اصلی بازگشتید:",
                    reply_markup=reply_markup
                )
                return ConversationHandler.END
            finally:
                if conn:
                    conn.close()
                    
        elif confirmation == "❌ خیر، انصراف":
            # بازگشت به منوی ویرایش همان دارو
            keyboard = [
                ['✏️ ویرایش تاریخ'],
                ['✏️ ویرایش تعداد'],
                ['🗑️ حذف دارو'],
                ['🔙 بازگشت به لیست داروها']
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"ویرایش دارو:\n\n"
                f"💊 نام: {drug['name']}\n"
                f"💰 قیمت: {drug['price']}\n"
                f"📅 تاریخ انقضا: {drug['date']}\n"
                f"📦 تعداد: {drug['quantity']}\n\n"
                "لطفا گزینه مورد نظر را انتخاب کنید:",
                reply_markup=reply_markup
            )
            return States.EDIT_DRUG
            
    except Exception as e:
        logger.error(f"Error in handle_drug_deletion_confirmation: {e}")
        
        # در صورت خطا به منوی اصلی برگرد
        context.user_data.clear()
        
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "❌ خطا در پردازش درخواست.\n\nبه منوی اصلی بازگشتید:",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
async def edit_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit specific drug item"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()

        if query.data == "back":
            return await list_my_drugs(update, context)
        
        if query.data.startswith("edit_drug_"):
            drug_id = int(query.data.split("_")[2])
            
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                    cursor.execute('''
                    SELECT id, name, price, date, quantity 
                    FROM drug_items 
                    WHERE id = %s AND user_id = %s
                    ''', (drug_id, update.effective_user.id))
                    drug = cursor.fetchone()
                    
                    if not drug:
                        await query.edit_message_text("دارو یافت نشد.")
                        return ConversationHandler.END
                    
                    # ذخیره اطلاعات دارو در context
                    context.user_data['editing_drug'] = {
                        'id': drug['id'],
                        'name': drug['name'],
                        'price': drug['price'],
                        'date': drug['date'],
                        'quantity': drug['quantity']
                    }
                    
                    keyboard = [
                        [InlineKeyboardButton("✏️ ویرایش تاریخ", callback_data="edit_date")],
                        [InlineKeyboardButton("✏️ ویرایش تعداد", callback_data="edit_quantity")],
                        [InlineKeyboardButton("🗑️ حذف دارو", callback_data="delete_drug")],
                        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_list")]
                    ]
                    
                    await query.edit_message_text(
                        f"ویرایش دارو:\n\n"
                        f"نام: {drug['name']}\n"
                        f"قیمت: {drug['price']}\n"
                        f"تاریخ انقضا: {drug['date']}\n"
                        f"تعداد: {drug['quantity']}\n\n"
                        "لطفا گزینه مورد نظر را انتخاب کنید:",
                        reply_markup=InlineKeyboardMarkup(keyboard))
                    return States.EDIT_DRUG
                    
            except Exception as e:
                logger.error(f"Error getting drug details: {e}")
                await query.edit_message_text("خطا در دریافت اطلاعات دارو.")
                return ConversationHandler.END
            finally:
                if conn:
                    conn.close()
    except Exception as e:
        logger.error(f"Error in edit_drug_item: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
async def handle_back_from_edit_drug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت بازگشت از ویرایش دارو - تشخیص نوع بازگشت"""
    try:
        if not update.message:
            return ConversationHandler.END
            
        text = update.message.text.strip()
        
        if text == "🔙 بازگشت به منوی اصلی":
            # پاک کردن کامل اطلاعات ویرایش از context
            context.user_data.clear()
            
            # نمایش منوی اصلی
            keyboard = [
                ['اضافه کردن دارو', 'جستجوی دارو'],
                ['لیست داروهای من', 'ثبت نیاز جدید'],
                ['لیست نیازهای من', 'ساخت کد پرسنل'],
                ['تنظیم شاخه‌های دارویی']
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                "به منوی اصلی بازگشتید. لطفاً یک گزینه را انتخاب کنید:",
                reply_markup=reply_markup
            )
            
            return ConversationHandler.END
            
        elif text == "🔙 بازگشت به لیست داروها":
            # بازگشت به لیست داروها (نه منوی اصلی)
            return await list_my_drugs(update, context)
            
        else:
            # اگر متن شناخته شده نیست، به منوی اصلی برگرد
            return await clear_conversation_state(update, context)
        
    except Exception as e:
        logger.error(f"Error in handle_back_from_edit_drug: {e}")
        return await clear_conversation_state(update, context)
async def handle_drug_edit_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drug edit action selection"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()

        if query.data == "back_to_list":
            return await edit_drugs(update, context)
        
        drug = context.user_data.get('editing_drug')
        if not drug:
            await query.edit_message_text("اطلاعات دارو یافت نشد.")
            return ConversationHandler.END
        
        if query.data == "edit_date":
            await query.edit_message_text(
                f"تاریخ فعلی: {drug['date']}\n\n"
                "لطفا تاریخ جدید را وارد کنید (مثال: 1403/05/15):"
            )
            context.user_data['edit_field'] = 'date'
            return States.EDIT_DRUG
        
        elif query.data == "edit_quantity":
            await query.edit_message_text(
                f"تعداد فعلی: {drug['quantity']}\n\n"
                "لطفا تعداد جدید را وارد کنید:"
            )
            context.user_data['edit_field'] = 'quantity'
            return States.EDIT_DRUG
        
        elif query.data == "delete_drug":
            keyboard = [
                [InlineKeyboardButton("✅ بله، حذف شود", callback_data="confirm_delete")],
                [InlineKeyboardButton("❌ خیر، انصراف", callback_data="cancel_delete")]
            ]
            
            await query.edit_message_text(
                f"آیا مطمئن هستید که می‌خواهید داروی {drug['name']} را حذف کنید؟",
                reply_markup=InlineKeyboardMarkup(keyboard))
            return States.EDIT_DRUG
            
    except Exception as e:
        logger.error(f"Error in handle_drug_edit_action: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def save_drug_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره ویرایش تاریخ یا تعداد دارو و بازگشت صحیح"""
    try:
        user_input = update.message.text.strip()
        
        # اول بررسی کن اگر کاربر می‌خواهد بازگردد
        if user_input in ["🔙 بازگشت", "🔙 بازگشت به لیست داروها", "🔙 بازگشت به منوی اصلی"]:
            return await clear_conversation_state(update, context)
        
        edit_field = context.user_data.get('edit_field')
        new_value = user_input
        drug = context.user_data.get('editing_drug')
        
        if not edit_field or not drug:
            await update.message.reply_text("خطا در ویرایش. لطفا دوباره تلاش کنید.")
            return await clear_conversation_state(update, context)

        # اعتبارسنجی بر اساس فیلد
        if edit_field == 'quantity':
            try:
                # تبدیل اعداد فارسی به انگلیسی
                persian_to_english = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
                new_value = new_value.translate(persian_to_english)
                
                # استخراج فقط ارقام
                digits = ''.join(filter(str.isdigit, new_value))
                if not digits:
                    await update.message.reply_text("❌ لطفا یک عدد معتبر وارد کنید.")
                    return States.EDIT_DRUG
                    
                new_value = int(digits)
                if new_value <= 0:
                    await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید.")
                    return States.EDIT_DRUG
            except ValueError:
                await update.message.reply_text("لطفا یک عدد صحیح وارد کنید.")
                return States.EDIT_DRUG
        
        elif edit_field == 'date':
            # اعتبارسنجی فرمت تاریخ
            persian_to_english = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
            new_value = new_value.translate(persian_to_english)
            
            if not re.match(r'^\d{4}/\d{2}/\d{2}$', new_value):
                await update.message.reply_text(
                    "❌ فرمت تاریخ نامعتبر است.\n\n"
                    "لطفا تاریخ را به فرمت 2026/01/23 وارد کنید:"
                )
                return States.EDIT_DRUG
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    sql.SQL('''
                    UPDATE drug_items 
                    SET {} = %s 
                    WHERE id = %s AND user_id = %s
                    ''').format(sql.Identifier(edit_field)),
                    (new_value, drug['id'], update.effective_user.id)
                )
                conn.commit()
                
                field_name = "تاریخ انقضا" if edit_field == 'date' else "تعداد"
                await update.message.reply_text(
                    f"✅ ویرایش با موفقیت انجام شد!\n\n"
                    f"{field_name} به {new_value} تغییر یافت."
                )
                
                # Update context
                drug[edit_field] = new_value
                
        except Exception as e:
            logger.error(f"Error updating drug: {e}")
            await update.message.reply_text("خطا در ویرایش دارو. لطفا دوباره تلاش کنید.")
        finally:
            if conn:
                conn.close()
        
        # بازگشت به منوی ویرایش همان دارو
        keyboard = [
            ['✏️ ویرایش تاریخ'],
            ['✏️ ویرایش تعداد'],
            ['🗑️ حذف دارو'],
            ['🔙 بازگشت به لیست داروها']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            f"ویرایش دارو:\n\n"
            f"💊 نام: {drug['name']}\n"
            f"💰 قیمت: {drug['price']}\n"
            f"📅 تاریخ انقضا: {drug['date']}\n"
            f"📦 تعداد: {drug['quantity']}\n\n"
            "لطفا گزینه مورد نظر را انتخاب کنید:",
            reply_markup=reply_markup
        )
        return States.EDIT_DRUG
        
    except Exception as e:
        logger.error(f"Error in save_drug_edit: {e}")
        
        # در صورت خطا به منوی اصلی برگرد
        context.user_data.clear()
        
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "⚠️ خطایی در ویرایش رخ داد.\n\nبه منوی اصلی بازگشتید:",
            reply_markup=reply_markup
        )
        return ConversationHandler.END

async def handle_drug_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drug deletion confirmation"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()
        logger.info(f"Deletion callback received: {query.data}")

        drug = context.user_data.get('editing_drug')
        if not drug:
            logger.error("No drug data found in context")
            await query.edit_message_text("اطلاعات دارو یافت نشد.")
            return ConversationHandler.END

        if query.data == "cancel_delete":
            logger.info("Deletion cancelled by user")
            # Return to drug edit menu
            keyboard = [
                [InlineKeyboardButton("✏️ ویرایش تاریخ", callback_data="edit_date")],
                [InlineKeyboardButton("✏️ ویرایش تعداد", callback_data="edit_quantity")],
                [InlineKeyboardButton("🗑️ حذف دارو", callback_data="delete_drug")],
                [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="back_to_list")]
            ]
            
            await query.edit_message_text(
                f"ویرایش دارو:\n\n"
                f"نام: {drug['name']}\n"
                f"تاریخ انقضا: {drug['date']}\n"
                f"تعداد: {drug['quantity']}\n\n"
                "لطفا گزینه مورد نظر را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard))
            return States.EDIT_DRUG

        elif query.data == "confirm_delete":
            logger.info(f"Confirming deletion of drug: {drug['name']}")
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor() as cursor:
                    cursor.execute('''
                    DELETE FROM drug_items 
                    WHERE id = %s AND user_id = %s
                    RETURNING id
                    ''', (drug['id'], update.effective_user.id))
                    
                    deleted_id = cursor.fetchone()
                    if not deleted_id:
                        logger.warning("No rows affected by deletion")
                        await query.edit_message_text("دارو یافت نشد یا قبلاً حذف شده است.")
                        return States.EDIT_DRUG
                    
                    conn.commit()
                    logger.info(f"Drug {drug['name']} deleted successfully")
                    
                    # Edit current message first
                    await query.edit_message_text(
                        f"✅ داروی {drug['name']} با موفقیت حذف شد.",
                        reply_markup=None
                    )
                    
                    # Then send a new message with drugs list
                    try:
                        # Clear any existing reply markup
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text="در حال بارگذاری لیست داروها...",
                            reply_markup=ReplyKeyboardRemove()
                        )
                        
                        # Call list_my_drugs with fresh context
                        fresh_update = Update(
                            update.update_id,
                            message=Message(
                                message_id=update.effective_message.message_id + 1,
                                date=update.effective_message.date,
                                chat=update.effective_chat,
                                text="لیست داروهای من"
                            )
                        )
                        return await list_my_drugs(fresh_update, context)
                    except Exception as e:
                        logger.error(f"Error showing drugs list: {e}")
                        # Fallback to main menu if list fails
                        keyboard = [
                            ['اضافه کردن دارو', 'جستجوی دارو'],
                            ['تنظیم شاخه‌های دارویی', 'لیست داروهای من'],
                            ['ثبت نیاز جدید', 'لیست نیازهای من']
                        ]
                        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text="به منوی اصلی بازگشتید:",
                            reply_markup=reply_markup
                        )
                        return ConversationHandler.END
                    
            except Exception as e:
                logger.error(f"Database error during deletion: {e}")
                if conn:
                    conn.rollback()
                await query.edit_message_text("خطا در حذف دارو. لطفا دوباره تلاش کنید.")
                return States.EDIT_DRUG
            finally:
                if conn:
                    conn.close()
        else:
            logger.warning(f"Unexpected callback data: {query.data}")
            await query.edit_message_text("عملیات نامعتبر است.")
            return States.EDIT_DRUG
            
    except Exception as e:
        logger.error(f"Error in handle_drug_deletion: {e}")
        try:
            await query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        except Exception as e:
            logger.error(f"Failed to edit message: {e}")
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="خطایی رخ داده است. لطفا دوباره تلاش کنید."
                )
            except Exception as e:
                logger.error(f"Failed to send error message: {e}")
        return ConversationHandler.END
# Needs Management
async def add_need(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start process to add a need with drug search"""
    await clear_conversation_state(update, context, silent=True)
    try:
        await ensure_user(update, context)
        
        # 🔥 تنظیم state برای تشخیص در اینلاین کوئری
        context.user_data['_conversation_state'] = States.SEARCH_DRUG_FOR_NEED
        
        # ایجاد دکمه برای جستجوی اینلاین برای نیاز
        keyboard = [
            [InlineKeyboardButton(
                "🔍 جستجوی دارو برای نیاز", 
                switch_inline_query_current_chat="need "
            )]
            
        ]
        
        await update.message.reply_text(
            "برای ثبت نیاز جدید، روی دکمه جستجو کلیک کنید و داروی مورد نیاز را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.SEARCH_DRUG_FOR_NEED
    except Exception as e:
        logger.error(f"Error in add_need: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def handle_need_drug_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drug selection for need from inline query (alternate entrypoint)"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data.startswith("need_drug_"):
            idx = int(query.data.split("_")[2])
            if 0 <= idx < len(drug_list):
                selected_drug = drug_list[idx]
                # Store selected drug for the need
                context.user_data['selected_drug_for_need'] = {
                    'name': selected_drug[0],
                    'price': selected_drug[1]
                }
                # Also set need_name so we don't require a separate description step
                context.user_data['need_name'] = selected_drug[0]
                
                await query.edit_message_text(
                    f"✅ داروی مورد نیاز انتخاب شد: {selected_drug[0]}\n💰 قیمت مرجع: {selected_drug[1]}\n\n"
                    "📦 لطفا تعداد مورد نیاز را وارد کنید:"
                )
                return States.ADD_NEED_QUANTITY
                
    except Exception as e:
        logger.error(f"Error handling need drug selection: {e}")
        await query.edit_message_text("خطا در انتخاب دارو. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def save_need_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save need name"""
    try:
        context.user_data['need_name'] = update.message.text
        await update.message.reply_text("لطفا توضیحاتی درباره این نیاز وارد کنید (اختیاری):")
        return States.ADD_NEED_DESC
    except Exception as e:
        logger.error(f"Error in save_need_name: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def save_need_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save need description"""
    await clear_conversation_state(update, context, silent=True)
    try:
        context.user_data['need_desc'] = update.message.text
        
        # ارسال پیام برای دریافت تعداد
        await update.message.reply_text(
            "📦 لطفا تعداد مورد نیاز را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        
        return States.ADD_NEED_QUANTITY
        
    except Exception as e:
        logger.error(f"Error in save_need_desc: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
# --- NEW FUNCTION: add_need_quantity (replace or add into bot.py) ---
async def add_need_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت تعداد برای نیاز دارو"""
    try:
        if not update or not update.message:
            logger.error("Invalid update in add_need_quantity")
            return States.ADD_NEED_QUANTITY
            
        text = update.message.text.strip()
        
        # بررسی اگر کاربر منوی دیگری انتخاب کرده باشد
        menu_options = ['اضافه کردن دارو', 'جستجوی دارو', 'لیست داروهای من', 
                       'ثبت نیاز جدید', 'لیست نیازهای من', 'ساخت کد پرسنل', 
                       'تنظیم شاخه‌های دارویی']
        
        if text in menu_options:
            # کاربر منوی دیگری انتخاب کرده، state را پاک کرده و به منوی اصلی برو
            context.user_data.clear()
            return await handle_state_change(update, context)
        
        quantity_text = text
        
        # بررسی وجود اطلاعات لازم
        if 'need_name' not in context.user_data:
            await update.message.reply_text(
                "❌ اطلاعات دارو از دست رفته. لطفا دوباره از ابتدا شروع کنید.",
                reply_markup=ReplyKeyboardRemove()
            )
            return await clear_conversation_state(update, context)
            
        need_name = context.user_data['need_name']
        
        try:
            # تبدیل اعداد فارسی به انگلیسی
            persian_to_english = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
            quantity_text = quantity_text.translate(persian_to_english)
            
            # استخراج فقط ارقام
            digits = ''.join(filter(str.isdigit, quantity_text))
            if not digits:
                await update.message.reply_text("❌ لطفا یک عدد معتبر وارد کنید:")
                return States.ADD_NEED_QUANTITY
                
            quantity = int(digits)
            if quantity <= 0:
                await update.message.reply_text("❌ تعداد باید بزرگتر از صفر باشد:")
                return States.ADD_NEED_QUANTITY
                
        except ValueError:
            await update.message.reply_text("❌ لطفا یک عدد معتبر وارد کنید:")
            return States.ADD_NEED_QUANTITY
            
        # ذخیره نیاز در دیتابیس
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                INSERT INTO user_needs (user_id, name, description, quantity)
                VALUES (%s, %s, %s, %s)
                ''', (
                    update.effective_user.id,
                    need_name,
                    need_name,  # استفاده از نام به عنوان توضیح
                    quantity
                ))
                conn.commit()
                
                await update.message.reply_text(
                    f"✅ نیاز «{need_name}» با تعداد {quantity} با موفقیت ثبت شد!",
                    reply_markup=ReplyKeyboardRemove()
                )
                
        except Exception as e:
            logger.error(f"Error saving need: {e}")
            if conn:
                conn.rollback()
            await update.message.reply_text("❌ خطا در ثبت نیاز. لطفا دوباره تلاش کنید.")
        finally:
            if conn:
                conn.close()
                
        # 🔥 پاک‌سازی کامل - حذف همه اطلاعات از جمله اطلاعات مبادله
        context.user_data.clear()
        
        # نمایش منوی اصلی
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "به منوی اصلی بازگشتید. لطفاً یک گزینه را انتخاب کنید:",
            reply_markup=reply_markup
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in add_need_quantity: {e}")
        await update.message.reply_text("❌ خطایی رخ داد. به منوی اصلی بازگشتید.")
        
        # پاک‌سازی کامل در صورت خطا
        context.user_data.clear()
        
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "به منوی اصلی بازگشتید:",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
# --- CHANGES TO ConversationHandler: needs_handler ---
# Replace the existing mapping for States.ADD_NEED_QUANTITY so it uses add_need_quantity.
# Find the needs_handler declaration and update the states dict entry:
#
#   States.ADD_NEED_QUANTITY: [
#       MessageHandler(filters.TEXT & ~filters.COMMAND, save_need)
#   ],
#
# Change it to:
#
#   States.ADD_NEED_QUANTITY: [
#       MessageHandler(filters.TEXT & ~filters.COMMAND, add_need_quantity)
#   ],
#
# (This ensures both inline-search -> select drug -> "enter quantity" flows and
# the chosen-inline-result flows are handled by the new function.)
#
# Note: if you prefer to keep the old save_need for the flow that first asks for
# name and description (ADD_NEED_NAME -> ADD_NEED_DESC -> ADD_NEED_QUANTITY), you can
# alternatively register both handlers in the same state with a small wrapper that
# chooses which implementation to call. The implementation above is self-contained
# and replaces save_need behavior for the ADD_NEED_QUANTITY step.
#
# --- Example replacement snippet for the needs_handler states block ---
#
# needs_handler = ConversationHandler(
#     entry_points=[ ... ],
#     states={
#         States.SEARCH_DRUG_FOR_NEED: [ ... ],
#         States.ADD_NEED_QUANTITY: [
#             MessageHandler(filters.TEXT & ~filters.COMMAND, add_need_quantity)
#         ],
#         States.EDIT_NEED: [ ... ]
#     },
#     fallbacks=[ ... ],
#     allow_reentry=True
# )
#
# Make sure to import/define add_need_quantity above where the needs_handler is constructed.

async def save_need(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Validate quantity and save a user need reliably, then return to main menu."""
    try:
        if not update.message or not update.message.text:
            logger.warning("save_need called without message text")
            await update.message.reply_text("ورودی نامعتبر است. لطفاً یک عدد وارد کنید.")
            return States.ADD_NEED_QUANTITY

        quantity_text = update.message.text.strip()
        # تبدیل ارقام فارسی به انگلیسی و حذف فضاها
        persian_to_english = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
        quantity_text = quantity_text.translate(persian_to_english)
        # استخراج فقط ارقام (در صورت وارد شدن متن به همراه واحد)
        digits = ''.join(ch for ch in quantity_text if ch.isdigit())
        if not digits:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید (مثال: 10).")
            return States.ADD_NEED_QUANTITY

        try:
            quantity = int(digits)
            if quantity <= 0:
                await update.message.reply_text("❌ تعداد باید بزرگتر از صفر باشد. دوباره وارد کنید:")
                return States.ADD_NEED_QUANTITY
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید (مثال: 10).")
            return States.ADD_NEED_QUANTITY

        # تعیین نام نیاز (از چند کلید ممکن)
        need_name = context.user_data.get('need_name')
        if not need_name:
            # بعضی مسیرها از selected_drug_for_need استفاده می‌کنند
            sel = context.user_data.get('selected_drug_for_need') or context.user_data.get('need_drug')
            if sel and isinstance(sel, dict):
                need_name = sel.get('name')

        need_desc = context.user_data.get('need_desc', '') or ''

        if not need_name:
            # اگر هنوز نام مشخص نیست از کاربر بخواهیم
            await update.message.reply_text("❌ نام دارو مشخص نیست. لطفا نام دارو را وارد کنید:")
            return States.ADD_NEED_NAME

        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO user_needs (user_id, name, description, quantity)
                    VALUES (%s, %s, %s, %s)
                ''', (update.effective_user.id, need_name, need_desc, quantity))
                conn.commit()
                logger.info(f"Saved need for user {update.effective_user.id}: {need_name} x{quantity}")
        except psycopg2.Error as e:
            logger.error(f"DB error in save_need: {e}", exc_info=True)
            if conn:
                conn.rollback()
            await update.message.reply_text("❌ خطا در ذخیره نیاز. دوباره تلاش کنید.")
            return States.ADD_NEED_QUANTITY
        finally:
            if conn:
                conn.close()

        # پاک‌سازی تنها کلیدهای مرتبط با جریان ثبت نیاز (نه کل context)
        for k in ['need_name', 'need_desc', 'need_drug', 'selected_drug_for_need']:
            context.user_data.pop(k, None)

        # پیام تأیید به کاربر
        await update.message.reply_text(
            f"✅ نیاز «{need_name}» با تعداد {quantity} با موفقیت ثبت شد!\n"
            f"{'توضیحات: ' + need_desc if need_desc else ''}",
            reply_markup=ReplyKeyboardRemove()
        )

        # نمایش منوی اصلی صریح (بدون استفاده از clear_conversation_state که ممکن است stateهای دیگر را پاک کند)
        main_keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="به منوی اصلی بازگشتید. لطفاً یک گزینه را انتخاب کنید:",
            reply_markup=reply_markup
        )

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error in save_need: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ خطایی رخ داد. از منوی اصلی شروع کنید.")
        except Exception as send_e:
            logger.error(f"Failed to send error message in save_need: {send_e}")
        # در صورت خطای غیرمنتظره، به منوی اصلی برو
        main_keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id if update and update.effective_chat else None,
                text="به منوی اصلی بازگشتید:",
                reply_markup=reply_markup
            )
        except Exception:
            pass
        return ConversationHandler.END

async def list_my_needs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست نیازهای کاربر با دکمه ویرایش در کیبورد معمولی"""
    user_id = update.effective_user.id
    logger.info(f"Starting list_my_needs for user {user_id}")
    conn = None
    try:
        conn = get_db_connection()
        logger.info(f"DB connection successful for user {user_id}")
        with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
            cursor.execute('''
                SELECT id, name, description, quantity
                FROM user_needs
                WHERE user_id = %s
                ORDER BY created_at DESC
            ''', (user_id,))
            needs = cursor.fetchall()
            logger.info(f"Query executed, found {len(needs)} needs for user {user_id}")
        
        if not needs:
            await update.message.reply_text("شما هیچ نیازی ثبت نکرده‌اید.")
            logger.info(f"No needs found for user {user_id}")
            return ConversationHandler.END
        
        message = "📋 لیست نیازهای شما:\n\n"
        for i, need in enumerate(needs, 1):
            desc = need['description'] or 'بدون توضیح'
            qty = need['quantity']
            # نمایش نام کامل بدون کوتاه کردن
            message += f"{i}. {need['name']}\n   توضیح: {desc}\n   تعداد: {qty}\n\n"
        
        # ایجاد کیبورد معمولی با دکمه ویرایش و بازگشت
        keyboard = [
            ['✏️ ویرایش نیازها'],
            ['🔙 بازگشت به منوی اصلی']  # تغییر این خط
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(message, reply_markup=reply_markup)
        logger.info(f"Needs list sent to user {user_id}")
        
        # ذخیره نیازها در context برای استفاده در ویرایش
        context.user_data['user_needs_list'] = needs
        
        return States.EDIT_NEED
        
    except psycopg2.OperationalError as op_e:
        logger.error(f"Operational DB error in list_my_needs for user {user_id}: {op_e}", exc_info=True)
        await update.message.reply_text("خطا در اتصال به دیتابیس. لطفا بررسی کنید که سرور postgres فعال است.")
        return ConversationHandler.END
    
    except psycopg2.Error as db_e:
        logger.error(f"DB error in list_my_needs for user {user_id}: {db_e}", exc_info=True)
        await update.message.reply_text("خطا در دریافت لیست نیازها از دیتابیس. لطفا جدول user_needs رو چک کنید.")
        return ConversationHandler.END
    
    except Exception as e:
        logger.error(f"Unexpected error in list_my_needs for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("خطا در نمایش لیست نیازها. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
    
    finally:
        if conn:
            conn.close()
            logger.info(f"DB connection closed for user {user_id}")
async def handle_edit_needs_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دکمه ویرایش نیازها در کیبورد معمولی"""
    try:
        if update.message.text == "✏️ ویرایش نیازها":
            return await edit_needs(update, context)
    except Exception as e:
        logger.error(f"Error in handle_edit_needs_button: {e}")
        await update.message.reply_text("خطا در پردازش درخواست ویرایش.")
    return States.EDIT_NEED
async def handle_back_from_edit_need(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت بازگشت از ویرایش نیاز - تشخیص نوع بازگشت"""
    try:
        if not update.message:
            return ConversationHandler.END
            
        text = update.message.text.strip()
        
        if text == "🔙 بازگشت به منوی اصلی":
            # پاک کردن کامل اطلاعات ویرایش از context
            context.user_data.clear()
            
            # نمایش منوی اصلی
            keyboard = [
                ['اضافه کردن دارو', 'جستجوی دارو'],
                ['لیست داروهای من', 'ثبت نیاز جدید'],
                ['لیست نیازهای من', 'ساخت کد پرسنل'],
                ['تنظیم شاخه‌های دارویی']
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                "به منوی اصلی بازگشتید. لطفاً یک گزینه را انتخاب کنید:",
                reply_markup=reply_markup
            )
            
            return ConversationHandler.END
            
        elif text == "🔙 بازگشت به لیست نیازها":
            # بازگشت به لیست نیازها (نه منوی اصلی)
            return await list_my_needs(update, context)
            
        else:
            # اگر متن شناخته شده نیست، به منوی اصلی برگرد
            return await clear_conversation_state(update, context)
        
    except Exception as e:
        logger.error(f"Error in handle_back_from_edit_need: {e}")
        return await clear_conversation_state(update, context)

async def edit_needs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع فرآیند ویرایش نیازها"""
    try:
        # حذف stateهای مربوط به داروها
        drug_keys = ['editing_drug', 'edit_field', 'current_selection']
        for key in drug_keys:
            context.user_data.pop(key, None)
        
        # استفاده از نیازهای ذخیره شده در context یا دریافت از دیتابیس
        needs = context.user_data.get('user_needs_list', [])
        
        if not needs:
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                    cursor.execute('''
                    SELECT id, name, description, quantity 
                    FROM user_needs 
                    WHERE user_id = %s
                    ORDER BY name
                    ''', (update.effective_user.id,))
                    needs = cursor.fetchall()
                    
            except Exception as e:
                logger.error(f"Error in edit_needs: {e}", exc_info=True)
                await update.message.reply_text("خطا در دریافت لیست نیازها.")
                return ConversationHandler.END
            finally:
                if conn:
                    conn.close()

        if not needs:
            await update.message.reply_text("هیچ نیازی برای ویرایش وجود ندارد.")
            return ConversationHandler.END
        
        # ساخت کیبورد برای انتخاب نیاز - با نام کامل
        keyboard = []
        for need in needs:
            # نمایش نام کامل بدون کوتاه کردن
            display_name = need['name']
            
            button_text = f"✏️ {display_name.strip()}"
            keyboard.append([button_text])
        
        keyboard.append(["🔙 بازگشت"])
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "لطفا نیازی که می‌خواهید ویرایش کنید را انتخاب کنید:",
            reply_markup=reply_markup
        )
        
        # ذخیره نیازها در context برای استفاده در مرحله بعد
        context.user_data['editing_needs_list'] = needs
        
        return States.EDIT_NEED
                
    except Exception as e:
        logger.error(f"Error in edit_needs: {e}", exc_info=True)
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
async def handle_select_need_for_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت انتخاب نیاز خاص برای ویرایش"""
    try:
        if not update.message:
            return States.EDIT_NEED
            
        selection = update.message.text
        
        # 🔥 اولویت اول: بررسی دکمه‌های بازگشت
        if selection in ["🔙 بازگشت", "🔙 بازگشت به لیست نیازها", "🔙 بازگشت به منوی اصلی"]:
            return await list_my_needs(update, context)
            
        # سپس: بررسی دکمه‌های عملیاتی
        if selection in ["✏️ ویرایش تعداد", "🗑️ حذف نیاز"]:
            return await handle_need_edit_action_from_keyboard(update, context)
            
        if selection in ["✅ بله، حذف شود", "❌ خیر، انصراف"]:
            return await handle_need_deletion_confirmation(update, context)
        
        # سپس بررسی انتخاب نیاز از لیست
        if selection.startswith("✏️ "):
            # استخراج نام کامل نیاز از دکمه
            need_name = selection[2:].strip()
            
            # دریافت لیست نیازها
            needs = context.user_data.get('editing_needs_list', [])
            if not needs:
                needs = context.user_data.get('user_needs_list', [])
            
            # اگر هنوز لیست نیازها موجود نیست، از دیتابیس بگیر
            if not needs:
                conn = None
                try:
                    conn = get_db_connection()
                    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                        cursor.execute('''
                        SELECT id, name, description, quantity 
                        FROM user_needs 
                        WHERE user_id = %s
                        ORDER BY name
                        ''', (update.effective_user.id,))
                        needs = cursor.fetchall()
                        context.user_data['editing_needs_list'] = needs
                except Exception as e:
                    logger.error(f"Error fetching needs from DB: {e}")
                finally:
                    if conn:
                        conn.close()
            
            # پیدا کردن نیاز انتخاب شده
            selected_need = None
            for need in needs:
                if need['name'].strip() == need_name:
                    selected_need = need
                    break
            
            if selected_need:
                context.user_data['editing_need'] = dict(selected_need)
                
                keyboard = [
                    ['✏️ ویرایش تعداد'],
                    ['🗑️ حذف نیاز'],
                    ['🔙 بازگشت به لیست نیازها']
                ]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                
                await update.message.reply_text(
                    f"ویرایش نیاز:\n\n"
                    f"💊 نام: {selected_need['name']}\n"
                    f"📝 توضیحات: {selected_need['description'] or 'بدون توضیح'}\n"
                    f"📦 تعداد: {selected_need['quantity']}\n\n"
                    "لطفا گزینه مورد نظر را انتخاب کنید:",
                    reply_markup=reply_markup
                )
                return States.EDIT_NEED
            else:
                await update.message.reply_text(
                    f"❌ نیاز «{need_name}» یافت نشد.\n\n"
                    "لطفا از لیست زیر یک نیاز را انتخاب کنید:"
                )
                return await edit_needs(update, context)
        
        # 🔥 اگر هیچکدام از موارد بالا نبود، احتمالاً کاربر عدد وارد کرده
        # اما ما در این state نباید عدد دریافت کنیم، پس خطا بده
        await update.message.reply_text(
            "❌ لطفا یکی از گزینه‌های موجود را انتخاب کنید.",
            reply_markup=ReplyKeyboardMarkup([
                ['✏️ ویرایش تعداد'],
                ['🗑️ حذف نیاز'],
                ['🔙 بازگشت به لیست نیازها']
            ], resize_keyboard=True)
        )
        return States.EDIT_NEED
        
    except Exception as e:
        logger.error(f"Error in handle_select_need_for_edit: {e}", exc_info=True)
        try:
            if update.message:
                await update.message.reply_text("خطا در انتخاب نیاز.")
        except:
            pass
        return States.EDIT_NEED
async def edit_need_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit specific need item"""
    try:
        # بررسی وجود callback query
        if not update.callback_query:
            logger.error("No callback query in edit_need_item")
            return ConversationHandler.END
            
        query = update.callback_query
        await query.answer()

        if query.data == "back":
            return await list_my_needs(update, context)
        
        if query.data.startswith("edit_need_"):
            need_id = int(query.data.split("_")[2])
            
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                    cursor.execute('''
                    SELECT id, name, description, quantity 
                    FROM user_needs 
                    WHERE id = %s AND user_id = %s
                    ''', (need_id, update.effective_user.id))
                    need = cursor.fetchone()
                    
                    if not need:
                        await query.edit_message_text("نیاز یافت نشد.")
                        return ConversationHandler.END
                    
                    context.user_data['editing_need'] = dict(need)
                    
                    keyboard = [
                        [InlineKeyboardButton("✏️ ویرایش نام", callback_data="edit_need_name")],
                        [InlineKeyboardButton("✏️ ویرایش توضیحات", callback_data="edit_need_desc")],
                        [InlineKeyboardButton("✏️ ویرایش تعداد", callback_data="edit_need_quantity")],
                        [InlineKeyboardButton("🗑️ حذف نیاز", callback_data="delete_need")],
                        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_needs_list")]
                    ]
                    
                    await query.edit_message_text(
                        f"ویرایش نیاز:\n\n"
                        f"نام: {need['name']}\n"
                        f"توضیحات: {need['description'] or 'بدون توضیح'}\n"
                        f"تعداد: {need['quantity']}\n\n"
                        "لطفا گزینه مورد نظر را انتخاب کنید:",
                        reply_markup=InlineKeyboardMarkup(keyboard))
                    return States.EDIT_NEED
                    
            except Exception as e:
                logger.error(f"Error getting need details: {e}")
                await query.edit_message_text("خطا در دریافت اطلاعات نیاز.")
                return ConversationHandler.END
            finally:
                if conn:
                    conn.close()
                    
    except Exception as e:
        logger.error(f"Error in edit_need_item: {e}")
        try:
            if update.callback_query:
                await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        except:
            pass
        return ConversationHandler.END
async def handle_need_edit_action_from_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle need edit actions from keyboard buttons - فقط ویرایش تعداد و حذف"""
    try:
        if not update.message:
            logger.error("No message in handle_need_edit_action_from_keyboard")
            return States.EDIT_NEED
            
        action = update.message.text
        need = context.user_data.get('editing_need')
        
        if not need:
            await update.message.reply_text("❌ ابتدا یک نیاز را برای ویرایش انتخاب کنید.")
            return await edit_needs(update, context)
        
        # ❌ ویرایش نام و توضیحات حذف شد
        # ✅ فقط ویرایش تعداد و حذف
        if action == "✏️ ویرایش تعداد":
            await update.message.reply_text(
                f"تعداد فعلی: {need['quantity']}\n\nلطفا تعداد جدید را وارد کنید:",
                reply_markup=ReplyKeyboardRemove()
            )
            context.user_data['edit_field'] = 'quantity'
            return States.EDIT_NEED
            
        elif action == "🗑️ حذف نیاز":
            keyboard = [
                ['✅ بله، حذف شود'],
                ['❌ خیر، انصراف']
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"⚠️ آیا مطمئن هستید که می‌خواهید نیاز «{need['name']}» را حذف کنید؟",
                reply_markup=reply_markup
            )
            return States.EDIT_NEED
            
    except Exception as e:
        logger.error(f"Error in handle_need_edit_action_from_keyboard: {e}")
        await update.message.reply_text("❌ خطا در پردازش درخواست.")
        return States.EDIT_NEED
async def handle_need_deletion_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle need deletion confirmation from keyboard"""
    try:
        if not update.message:
            return States.EDIT_NEED
            
        confirmation = update.message.text
        need = context.user_data.get('editing_need')
        
        if not need:
            await update.message.reply_text("❌ اطلاعات نیاز یافت نشد.")
            return await clear_conversation_state(update, context)
        
        if confirmation == "✅ بله، حذف شود":
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor() as cursor:
                    # 🔥 ابتدا رکوردهای مربوطه در match_notifications را حذف کنیم
                    cursor.execute(
                        'DELETE FROM match_notifications WHERE need_id = %s',
                        (need['id'],)
                    )
                    logger.info(f"Deleted {cursor.rowcount} match notifications for need {need['id']}")
                    
                    # سپس نیاز را حذف کنیم
                    cursor.execute(
                        'DELETE FROM user_needs WHERE id = %s AND user_id = %s',
                        (need['id'], update.effective_user.id)
                    )
                    deleted_rows = cursor.rowcount
                    conn.commit()
                    
                    if deleted_rows > 0:
                        # 🔥 پاک‌سازی کامل و بازگشت به منوی اصلی
                        context.user_data.clear()
                        
                        keyboard = [
                            ['اضافه کردن دارو', 'جستجوی دارو'],
                            ['لیست داروهای من', 'ثبت نیاز جدید'],
                            ['لیست نیازهای من', 'ساخت کد پرسنل'],
                            ['تنظیم شاخه‌های دارویی']
                        ]
                        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                        
                        await update.message.reply_text(
                            f"✅ نیاز «{need['name']}» با موفقیت حذف شد.\n\nبه منوی اصلی بازگشتید:",
                            reply_markup=reply_markup
                        )
                        return ConversationHandler.END
                    else:
                        await update.message.reply_text(
                            "❌ نیاز یافت نشد یا قبلاً حذف شده است.",
                            reply_markup=ReplyKeyboardRemove()
                        )
                        return await clear_conversation_state(update, context)
                    
            except Exception as e:
                logger.error(f"Error deleting need {need['id']}: {e}")
                if conn:
                    conn.rollback()
                
                # پاک‌سازی و بازگشت به منوی اصلی در صورت خطا
                context.user_data.clear()
                
                keyboard = [
                    ['اضافه کردن دارو', 'جستجوی دارو'],
                    ['لیست داروهای من', 'ثبت نیاز جدید'],
                    ['لیست نیازهای من', 'ساخت کد پرسنل'],
                    ['تنظیم شاخه‌های دارویی']
                ]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                
                await update.message.reply_text(
                    "❌ خطا در حذف نیاز.\n\nبه منوی اصلی بازگشتید:",
                    reply_markup=reply_markup
                )
                return ConversationHandler.END
            finally:
                if conn:
                    conn.close()
                    
        elif confirmation == "❌ خیر، انصراف":
            # بازگشت به منوی ویرایش همان نیاز
            keyboard = [
                ['✏️ ویرایش تعداد'],
                ['🗑️ حذف نیاز'],
                ['🔙 بازگشت به لیست نیازها']
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"ویرایش نیاز:\n\n"
                f"💊 نام: {need['name']}\n"
                f"📝 توضیحات: {need['description'] or 'بدون توضیح'}\n"
                f"📦 تعداد: {need['quantity']}\n\n"
                "لطفا گزینه مورد نظر را انتخاب کنید:",
                reply_markup=reply_markup
            )
            return States.EDIT_NEED
            
    except Exception as e:
        logger.error(f"Error in handle_need_deletion_confirmation: {e}")
        
        # در صورت خطا به منوی اصلی برگرد
        context.user_data.clear()
        
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "❌ خطا در پردازش درخواست.\n\nبه منوی اصلی بازگشتید:",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
async def handle_need_edit_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle need edit action selection"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()

        if query.data == "back_to_needs_list":
            return await edit_needs(update, context)
        
        need = context.user_data.get('editing_need')
        if not need:
            await query.edit_message_text("اطلاعات نیاز یافت نشد.")
            return ConversationHandler.END
        
        if query.data == "edit_need_name":
            await query.edit_message_text(
                f"نام فعلی: {need['name']}\n\n"
                "لطفا نام جدید را وارد کنید:"
            )
            context.user_data['edit_field'] = 'name'
            return States.EDIT_NEED
        
        elif query.data == "edit_need_desc":
            await query.edit_message_text(
                f"توضیحات فعلی: {need['description'] or 'بدون توضیح'}\n\n"
                "لطفا توضیحات جدید را وارد کنید:"
            )
            context.user_data['edit_field'] = 'description'
            return States.EDIT_NEED
        
        elif query.data == "edit_need_quantity":
            await query.edit_message_text(
                f"تعداد فعلی: {need['quantity']}\n\n"
                "لطفا تعداد جدید را وارد کنید:"
            )
            context.user_data['edit_field'] = 'quantity'
            return States.EDIT_NEED
        
        elif query.data == "delete_need":
            keyboard = [
                [InlineKeyboardButton("✅ بله، حذف شود", callback_data="confirm_need_delete")],
                [InlineKeyboardButton("❌ خیر، انصراف", callback_data="cancel_need_delete")]
            ]
            
            await query.edit_message_text(
                f"آیا مطمئن هستید که می‌خواهید نیاز {need['name']} را حذف کنید؟",
                reply_markup=InlineKeyboardMarkup(keyboard))
            return States.EDIT_NEED
    except Exception as e:
        logger.error(f"Error in handle_need_edit_action: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def save_need_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره ویرایش تعداد نیاز و بازگشت صحیح به منوی اصلی"""
    try:
        user_input = update.message.text.strip()
        
        # 🔥 اول بررسی کن اگر کاربر می‌خواهد بازگردد
        if user_input in ["🔙 بازگشت", "🔙 بازگشت به لیست نیازها", "🔙 بازگشت به منوی اصلی"]:
            return await clear_conversation_state(update, context)
        
        edit_field = context.user_data.get('edit_field')
        new_value = user_input
        need = context.user_data.get('editing_need')
        
        if not edit_field or not need:
            await update.message.reply_text("خطا در ویرایش. لطفا دوباره تلاش کنید.")
            return await clear_conversation_state(update, context)

        # ❌ فقط برای تعداد
        if edit_field == 'quantity':
            try:
                # تبدیل اعداد فارسی به انگلیسی
                persian_to_english = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
                new_value = new_value.translate(persian_to_english)
                
                # استخراج فقط ارقام
                digits = ''.join(filter(str.isdigit, new_value))
                if not digits:
                    await update.message.reply_text("❌ لطفا یک عدد معتبر وارد کنید.")
                    return States.EDIT_NEED
                    
                new_value = int(digits)
                if new_value <= 0:
                    await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید.")
                    return States.EDIT_NEED
            except ValueError:
                await update.message.reply_text("لطفا یک عدد صحیح وارد کنید.")
                return States.EDIT_NEED
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    sql.SQL('''
                    UPDATE user_needs 
                    SET {} = %s 
                    WHERE id = %s AND user_id = %s
                    ''').format(sql.Identifier(edit_field)),
                    (new_value, need['id'], update.effective_user.id)
                )
                conn.commit()
                
                await update.message.reply_text(
                    f"✅ ویرایش با موفقیت انجام شد!\n\n"
                    f"تعداد به {new_value} تغییر یافت."
                )
                
                # Update context
                need[edit_field] = new_value
                
        except Exception as e:
            logger.error(f"Error updating need: {e}")
            await update.message.reply_text("خطا در ویرایش نیاز. لطفا دوباره تلاش کنید.")
        finally:
            if conn:
                conn.close()
        
        # 🔥 پاک‌سازی کامل context و بازگشت به منوی اصلی
        context.user_data.clear()
        
        # نمایش منوی اصلی با کیبورد استاندارد
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "✅ ویرایش نیاز با موفقیت انجام شد.\n\nبه منوی اصلی بازگشتید:",
            reply_markup=reply_markup
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in save_need_edit: {e}")
        
        # در صورت خطا هم به منوی اصلی برگرد
        context.user_data.clear()
        
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "⚠️ خطایی در ویرایش رخ داد.\n\nبه منوی اصلی بازگشتید:",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
async def handle_need_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle need deletion confirmation"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()

        if query.data == "cancel_need_delete":
            return await edit_need_item(update, context)
        
        need = context.user_data.get('editing_need')
        if not need:
            await query.edit_message_text("اطلاعات نیاز یافت نشد.")
            return ConversationHandler.END
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                DELETE FROM user_needs 
                WHERE id = %s AND user_id = %s
                ''', (need['id'], update.effective_user.id))
                conn.commit()
                
                await query.edit_message_text(
                    f"✅ نیاز {need['name']} با موفقیت حذف شد."
                )
                
        except Exception as e:
            logger.error(f"Error deleting need: {e}")
            await query.edit_message_text("خطا در حذف نیاز. لطفا دوباره تلاش کنید.")
        finally:
            if conn:
                conn.close()
        
        return await list_my_needs(update, context)
    except Exception as e:
        logger.error(f"Error in handle_need_deletion: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
# Drug Trading Functions
async def search_drug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start drug search process with main menu access"""
    await clear_conversation_state(update, context, silent=True)
    logger.info(f"search_drug called by user {update.effective_user.id}")
    try:
        # نمایش منوی اصلی همراه با درخواست جستجو
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "لطفا نام داروی مورد نظر را وارد کنید:\n\n",
            reply_markup=reply_markup
        )
        return States.SEARCH_DRUG
    except Exception as e:
        logger.error(f"Error in search_drug: {e}")
        await update.message.reply_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """جستجوی دارو و نمایش نتایج با دکمه اینلاین برای انتخاب داروخانه"""
    await clear_conversation_state(update, context, silent=True)
    try:
        # بررسی وجود update.message
        if not update.message:
            logger.error("No message in update for handle_search")
            # تلاش برای ارسال پیام از طریق context
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="خطا در پردازش درخواست. لطفا دوباره تلاش کنید."
                )
            except:
                pass
            return ConversationHandler.END
            
        drug_name = update.message.text.strip()
        user_id = update.effective_user.id
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                # محاسبه pharmacy_id واقعی
                cursor.execute('SELECT creator_id FROM users WHERE id = %s', (user_id,))
                result = cursor.fetchone()
                pharmacy_id = result['creator_id'] if result and result['creator_id'] else user_id

                # کوئری جستجو
                cursor.execute('''
                SELECT 
                    COALESCE(p.user_id, creator_p.user_id) as pharmacy_id,
                    COALESCE(p.name, creator_p.name) as pharmacy_name,
                    di.name as drug_name,
                    di.price,
                    di.quantity,
                    di.date
                FROM drug_items di
                LEFT JOIN pharmacies p ON di.user_id = p.user_id
                LEFT JOIN users u ON di.user_id = u.id
                LEFT JOIN pharmacies creator_p ON u.creator_id = creator_p.user_id
                WHERE 
                    di.name ILIKE %s AND 
                    di.quantity > 0 AND
                    (p.verified = TRUE OR creator_p.verified = TRUE) AND
                    COALESCE(p.user_id, creator_p.user_id) != %s
                ORDER BY COALESCE(p.name, creator_p.name), di.name
                LIMIT 20
                ''', (f'%{drug_name}%', pharmacy_id))
                
                results = cursor.fetchall()

                if not results:
                    # ایجاد کیبورد اصلی برای ادامه کار
                    main_keyboard = [
                        ['اضافه کردن دارو', 'جستجوی دارو'],
                        ['لیست داروهای من', 'ثبت نیاز جدید'],
                        ['لیست نیازهای من', 'ساخت کد پرسنل'],
                        ['تنظیم شاخه‌های دارویی']
                    ]
                    reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
                    
                    await update.message.reply_text(
                        "⚠️ هیچ داروخانه‌ای با این دارو پیدا نشد.\n\n"
                        "لطفاً نام داروی دیگری را جستجو کنید یا از منوی زیر اقدام کنید:",
                        reply_markup=reply_markup
                    )
                    return States.SEARCH_DRUG

                # گروه‌بندی نتایج بر اساس داروخانه
                pharmacy_results = {}
                for item in results:
                    pharmacy_id = item['pharmacy_id']
                    if pharmacy_id not in pharmacy_results:
                        pharmacy_results[pharmacy_id] = {
                            'name': item['pharmacy_name'],
                            'drugs': []
                        }
                    pharmacy_results[pharmacy_id]['drugs'].append(item)

                # ساخت پیام و کیبورد
                message = "🏥 نتایج جستجو:\n\n"
                keyboard = []
                
                for pharmacy_id, data in pharmacy_results.items():
                    pharmacy_name = data['name']
                    drugs = data['drugs']
                    
                    # اضافه کردن به پیام
                    message += f"🏥 {pharmacy_name}:\n"
                    for drug in drugs[:3]:  # حداکثر 3 دارو نمایش داده شود
                      message += f"  💊 {drug['drug_name']} - {drug['price']} - {drug['quantity']} عدد - 📅 {drug['date']}\n"
                    if len(drugs) > 3:
                        message += f"  ... و {len(drugs) - 3} داروی دیگر\n"
                    message += "\n"
                    
                    # اضافه کردن دکمه اینلاین
                    keyboard.append([
                        InlineKeyboardButton(
                            f"🏥 {pharmacy_name} ({len(drugs)} دارو)",
                            callback_data=f"pharmacy_{pharmacy_id}"
                        )
                    ])

                # اضافه کردن کیبورد اصلی برای ادامه کار
                main_keyboard = [
                    ['اضافه کردن دارو', 'جستجوی دارو'],
                    ['لیست داروهای من', 'ثبت نیاز جدید'],
                    ['لیست نیازهای من', 'ساخت کد پرسنل'],
                    ['تنظیم شاخه‌های دارویی']
                ]
                reply_markup_main = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
                
                # ارسال پیام با دکمه‌های اینلاین
                await update.message.reply_text(
                    message,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                # ارسال کیبورد اصلی به صورت جداگانه
                await update.message.reply_text(
                    " داروخانه مدنظر خود را انتخاب کنید ",
                    reply_markup=reply_markup_main
                )
                
                return States.SELECT_PHARMACY
                
        except Exception as e:
            logger.error(f"Database error in handle_search: {e}")
            
            # در صورت خطا هم کیبورد اصلی را نشان بده
            main_keyboard = [
                ['اضافه کردن دارو', 'جستجوی دارو'],
                ['لیست داروهای من', 'ثبت نیاز جدید'],
                ['لیست نیازهای من', 'ساخت کد پرسنل'],
                ['تنظیم شاخه‌های دارویی']
            ]
            reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                "خطا در جستجو. لطفاً دوباره تلاش کنید.",
                reply_markup=reply_markup
            )
        finally:
            if conn:
                conn.close()
                
    except Exception as e:
        logger.error(f"Error in handle_search: {e}")
        # استفاده از روش ایمن برای ارسال پیام
        try:
            if update.message:
                # نمایش کیبورد اصلی در صورت خطا
                main_keyboard = [
                    ['اضافه کردن دارو', 'جستجوی دارو'],
                    ['لیست داروهای من', 'ثبت نیاز جدید'],
                    ['لیست نیازهای من', 'ساخت کد پرسنل'],
                    ['تنظیم شاخه‌های دارویی']
                ]
                reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
                
                await update.message.reply_text(
                    "خطایی در پردازش جستجو رخ داد. لطفاً دوباره تلاش کنید.",
                    reply_markup=reply_markup
                )
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="خطایی در پردازش جستجو رخ داد."
                )
        except Exception as send_error:
            logger.error(f"Failed to send error message: {send_error}")
        return ConversationHandler.END
async def select_pharmacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pharmacy selection and initiate drug selection"""
    #await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()
        
        pharmacy_id = int(query.data.split('_')[1])
        context.user_data['selected_pharmacy_id'] = pharmacy_id
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('SELECT name FROM pharmacies WHERE user_id = %s', (pharmacy_id,))
                result = cursor.fetchone()
                pharmacy_name = result[0] if result else "داروخانه ناشناس"
                context.user_data['selected_pharmacy_name'] = pharmacy_name
        except Exception as e:
            logger.error(f"Error getting pharmacy name: {e}")
            pharmacy_name = "داروخانه ناشناس"
        finally:
            if conn:
                conn.close()
        
        # Initialize pagination
        context.user_data['page_target'] = 0
        context.user_data['page_mine'] = 0
        
        # Initialize selection lists
        context.user_data['offer_items'] = []
        context.user_data['comp_items'] = []
        
        await query.edit_message_text(f"داروخانه {pharmacy_name} انتخاب شد.\nدر حال بارگذاری داروها...")
        
        return await show_two_column_selection(update, context)
        
    except Exception as e:
        logger.error(f"Error in select_pharmacy: {e}")
        try:
            await query.edit_message_text("خطا در انتخاب داروخانه")
        except:
            await context.bot.send_message(chat_id=query.message.chat_id, text="خطا در انتخاب داروخانه")
    return States.SELECT_DRUGS


async def show_two_column_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش داروهای کاربر در صفحه اول و داروهای داروخانه هدف در صفحه دوم"""
    #await clear_conversation_state(update, context, silent=True)
    
    try:
        # تعیین متغیرهای اولیه
        chat_id = None
        reply_method = None
        use_chat_id = False

        if update.message:
            chat_id = update.message.chat_id
            reply_method = update.message.reply_text
        elif update.callback_query:
            chat_id = update.callback_query.message.chat_id
            reply_method = context.bot.send_message
            use_chat_id = True
        else:
            logger.error("Invalid update type in show_two_column_selection")
            return States.SELECT_DRUGS

        pharmacy_id = context.user_data.get('selected_pharmacy_id')
        user_id = update.effective_user.id
        
        if not pharmacy_id:
            error_text = "هیچ داروخانه‌ای انتخاب نشده است"
            if use_chat_id:
                await reply_method(chat_id=chat_id, text=error_text)
            else:
                await reply_method(text=error_text)
            return States.SELECT_PHARMACY
        
        # تعیین نوع لیست فعلی (کاربر یا هدف)
        current_list_type = context.user_data.get('current_list_type', 'mine')  # پیش‌فرض: داروهای کاربر
        page = context.user_data.get(f'page_{current_list_type}', 0)
        items_per_page = 5  # تعداد آیتم‌ها در هر صفحه
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                # دریافت نام داروخانه
                cursor.execute('SELECT name FROM pharmacies WHERE user_id = %s', (pharmacy_id,))
                pharmacy_result = cursor.fetchone()
                pharmacy_name = pharmacy_result['name'] if pharmacy_result else "داروخانه هدف"
                
                # دریافت داروها بر اساس نوع لیست
                if current_list_type == 'mine':
                    # داروهای کاربر
                    cursor.execute('''
                    SELECT id, name, price, quantity, date
                    FROM drug_items
                    WHERE user_id = %s AND quantity > 0
                    ORDER BY name
                    LIMIT %s OFFSET %s
                    ''', (user_id, items_per_page, page * items_per_page))
                    drugs = cursor.fetchall()
                    
                    cursor.execute('''
                    SELECT COUNT(*) FROM drug_items
                    WHERE user_id = %s AND quantity > 0
                    ''', (user_id,))
                    total_items = cursor.fetchone()['count']
                    list_title = "داروهای شما"
                else:
                    # داروهای داروخانه هدف
                    cursor.execute('''
                    SELECT id, name, price, quantity, date
                    FROM drug_items
                    WHERE user_id = %s AND quantity > 0
                    ORDER BY name
                    LIMIT %s OFFSET %s
                    ''', (pharmacy_id, items_per_page, page * items_per_page))
                    drugs = cursor.fetchall()
                    
                    cursor.execute('''
                    SELECT COUNT(*) FROM drug_items
                    WHERE user_id = %s AND quantity > 0
                    ''', (pharmacy_id,))
                    total_items = cursor.fetchone()['count']
                    list_title = f"داروهای {pharmacy_name}"
                
                # محاسبه مجموع‌ها
                offer_items = context.user_data.get('offer_items', [])
                comp_items = context.user_data.get('comp_items', [])
                
                offer_total = sum(parse_price(item['price']) * item['quantity'] for item in offer_items)
                comp_total = sum(parse_price(item['price']) * item['quantity'] for item in comp_items)
                price_difference = offer_total - comp_total
                
                # ساخت پیام
                message = f"💊 انتخاب دارو برای مبادله با {pharmacy_name}\n\n"
                message += f"📌 {list_title} (صفحه {page + 1} از {max(1, (total_items + items_per_page - 1) // items_per_page)}):\n"
                for i, drug in enumerate(drugs, 1):
                    message += f"{i}. {drug['name']} - {drug['price']}\n"
                    message += f"   📦 تعداد: {drug['quantity']} عدد | 📅 تاریخ: {drug['date']}\n"
                
                # نمایش خلاصه انتخاب‌ها
                if offer_items or comp_items:
                    message += f"\n📊 خلاصه انتخاب‌ها:\n"
                    if offer_items:
                        message += f"درخواستی: {len(offer_items)} دارو - {format_price(offer_total)}\n"
                    if comp_items:
                        message += f"جبرانی: {len(comp_items)} دارو - {format_price(comp_total)}\n"
                    message += f"اختلاف: {format_price(price_difference)}\n"
                
                # ذخیره داروها برای انتخاب
                context.user_data[f'{current_list_type}_drugs'] = drugs
                
                # ساخت کیبورد - به صورت عمودی
                keyboard = []
                
                # دکمه‌های انتخاب دارو - به صورت عمودی
                prefix = '💊' if current_list_type == 'mine' else '📌'
                for i, drug in enumerate(drugs, 1):
                    # هر دارو در یک سطر جداگانه
                    keyboard.append([KeyboardButton(f"{prefix} {i} - {drug['name']}")])
                
                # دکمه‌های صفحه‌بندی - به صورت عمودی
                if page > 0:
                    keyboard.append([KeyboardButton(f"{prefix} صفحه قبل")])
                if (page + 1) * items_per_page < total_items:
                    keyboard.append([KeyboardButton(f"{prefix} صفحه بعد")])
                
                # دکمه‌های جابجایی بین لیست‌ها - به صورت عمودی
                if current_list_type == 'mine':
                    keyboard.append([KeyboardButton("📌 داروهای داروخانه هدف")])
                else:
                    keyboard.append([KeyboardButton("💊 داروهای شما")])
                
                # دکمه‌های عملیاتی - به صورت عمودی
                if offer_items or comp_items:
                    keyboard.append([KeyboardButton("✅ اتمام انتخاب")])
                keyboard.append([KeyboardButton("🔙 بازگشت به منوی اصلی")])
                
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
                
                # ارسال یا ویرایش پیام
                if update.callback_query:
                    try:
                        await update.callback_query.delete_message()
                    except:
                        pass
                
                if use_chat_id:
                    await reply_method(chat_id=chat_id, text=message, reply_markup=reply_markup)
                else:
                    await reply_method(text=message, reply_markup=reply_markup)
                
                return States.SELECT_DRUGS
                
        except Exception as e:
            logger.error(f"Error in show_two_column_selection: {e}")
            error_text = "خطا در نمایش داروها"
            if use_chat_id:
                await reply_method(chat_id=chat_id, text=error_text)
            else:
                await reply_method(text=error_text)
        finally:
            if conn:
                conn.close()
                
    except Exception as e:
        logger.error(f"Error in show_two_column_selection: {e}")
        error_text = "خطا در نمایش داروها"
        if update.message:
            await update.message.reply_text(error_text)
        elif update.callback_query:
            await context.bot.send_message(chat_id=chat_id, text=error_text)
    return States.SELECT_DRUGS
async def handle_drug_selection_from_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب دارو از کیبورد"""
    try:
        selection = update.message.text.strip()
        current_list_type = context.user_data.get('current_list_type', 'mine')
        drugs = context.user_data.get(f'{current_list_type}_drugs', [])
        
        logger.info(f"User selected: {selection}")
        logger.info(f"Current list type: {current_list_type}")
        logger.info(f"Available drugs count: {len(drugs)}")
        
        # مدیریت دکمه‌های خاص
        if selection == "✅ اتمام انتخاب":
            return await handle_finish_selection(update, context)
        # تغییر این خط: به جای بازگشت به داروخانه‌ها، به منوی اصلی برگردد
        elif selection == "🔙 بازگشت به منوی اصلی":
            return await clear_conversation_state(update, context)
        elif selection == "📌 داروهای داروخانه هدف":
            context.user_data['current_list_type'] = 'target'
            context.user_data['page_target'] = 0
            return await show_two_column_selection(update, context)
        elif selection == "💊 داروهای شما":
            context.user_data['current_list_type'] = 'mine'
            context.user_data['page_mine'] = 0
            return await show_two_column_selection(update, context)
        elif "صفحه قبل" in selection:
            context.user_data[f'page_{current_list_type}'] = max(0, context.user_data.get(f'page_{current_list_type}', 0) - 1)
            return await show_two_column_selection(update, context)
        elif "صفحه بعد" in selection:
            context.user_data[f'page_{current_list_type}'] = context.user_data.get(f'page_{current_list_type}', 0) + 1
            return await show_two_column_selection(update, context)
        elif selection == "🗑️ پاک کردن همه انتخاب‌ها":
            context.user_data.pop('offer_items', None)
            context.user_data.pop('comp_items', None)
            await update.message.reply_text("✅ همه انتخاب‌ها پاک شدند.")
            return await show_two_column_selection(update, context)
        
        # پردازش انتخاب دارو
        prefix = '💊' if current_list_type == 'mine' else '📌'
        
        if selection.startswith(prefix):
            try:
                # استخراج شماره از انتخاب
                clean_selection = selection.replace(f"{prefix} ", "").strip()
                
                # حذف ✅ اگر وجود دارد
                clean_selection = clean_selection.replace("✅ ", "").strip()
                
                # استخراج عدد
                index_part = clean_selection.split(" - ")[0]
                index_str = ''.join(filter(str.isdigit, index_part))
                
                if not index_str:
                    raise ValueError("No digits found")
                    
                index = int(index_str) - 1
                
                logger.info(f"Extracted index: {index}, drugs count: {len(drugs)}")
                
                if 0 <= index < len(drugs):
                    drug = drugs[index]
                    context.user_data['current_selection'] = {
                        'id': drug['id'],
                        'name': drug['name'],
                        'price': drug['price'],
                        'quantity': drug['quantity'],
                        'date': drug['date'],
                        'type': current_list_type
                    }
                    
                    # ذخیره برای بازیابی
                    context.user_data['last_selection_info'] = {
                        **context.user_data['current_selection'],
                        'timestamp': time.time()
                    }
                    
                    await update.message.reply_text(
                        f"💊 داروی انتخاب شده: {drug['name']}\n"
                        f"💰 قیمت: {drug['price']}\n"
                        f"📅 تاریخ انقضا: {drug['date']}\n"
                        f"📦 موجودی: {drug['quantity']}\n\n"
                        f"لطفا تعداد مورد نظر را وارد کنید:",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    return States.SELECT_QUANTITY
                else:
                    await update.message.reply_text("شماره دارو نامعتبر است.")
                    return States.SELECT_DRUGS
                    
            except (ValueError, IndexError, AttributeError) as e:
                logger.error(f"Error parsing selection '{selection}': {e}")
                # ادامه به الگوی بعدی
        
        # الگوی جایگزین: فقط عدد وارد شده
        try:
            # تبدیل اعداد فارسی
            persian_to_english = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
            clean_selection = selection.translate(persian_to_english)
            
            index = int(''.join(filter(str.isdigit, clean_selection))) - 1
            if 0 <= index < len(drugs):
                drug = drugs[index]
                context.user_data['current_selection'] = {
                    'id': drug['id'],
                    'name': drug['name'],
                    'price': drug['price'],
                    'quantity': drug['quantity'],
                    'date': drug['date'],
                    'type': current_list_type
                }
                
                # ذخیره برای بازیابی
                context.user_data['last_selection_info'] = {
                    **context.user_data['current_selection'],
                    'timestamp': time.time()
                }
                
                await update.message.reply_text(
                    f"💊 داروی انتخاب شده: {drug['name']}\n"
                    f"💰 قیمت: {drug['price']}\n"
                    f"📅 تاریخ انقضا: {drug['date']}\n"
                    f"📦 موجودی: {drug['quantity']}\n\n"
                    f"لطفا تعداد مورد نظر را وارد کنید:",
                    reply_markup=ReplyKeyboardRemove()
                )
                return States.SELECT_QUANTITY
        except ValueError:
            pass  # ادامه به خطای پایانی
        
        # اگر هیچکدام از الگوها مطابقت نکرد
        logger.warning(f"Invalid selection: {selection}")
        
        await update.message.reply_text(
            "❌ لطفا یک گزینه معتبر از لیست انتخاب کنید یا شماره دارو را وارد نمایید.\n\n"
            "مثال:\n"
            "- روی دکمه '💊 1 - نام دارو' کلیک کنید\n"
            "- یا عدد '1' را وارد کنید",
            reply_markup=ReplyKeyboardRemove()
        )
        
        # نمایش مجدد لیست داروها
        return await show_two_column_selection(update, context)
        
    except Exception as e:
        logger.error(f"Error in handle_drug_selection_from_keyboard: {e}", exc_info=True)
        
        await update.message.reply_text(
            "❌ خطا در پردازش انتخاب!\n\n"
            "در حال بازگشت به لیست داروها...",
            reply_markup=ReplyKeyboardRemove()
        )
        
        # بازگشت به لیست داروها
        return await show_two_column_selection(update, context)

async def enter_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت تعداد برای داروی انتخاب شده و جمع کردن مقادیر تکراری"""
    try:
        quantity_text = update.message.text.strip()
        current_selection = context.user_data.get('current_selection')
        
        if not current_selection:
            logger.error("No current selection found in context")
            await update.message.reply_text("انتخاب دارو از دست رفته. لطفا دوباره از لیست انتخاب کنید.")
            return await show_two_column_selection(update, context)
        
        # پردازش تعداد
        try:
            # تبدیل اعداد فارسی به انگلیسی
            persian_to_english = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
            quantity_text = quantity_text.translate(persian_to_english)
            
            quantity = int(''.join(filter(str.isdigit, quantity_text)))
            if quantity <= 0:
                await update.message.reply_text(
                    f"❌ لطفا عددی بزرگتر از صفر وارد کنید.\nموجودی قابل دسترس: {current_selection['quantity']}"
                )
                return States.SELECT_QUANTITY
                
            if quantity > current_selection['quantity']:
                await update.message.reply_text(
                    f"❌ تعداد وارد شده بیشتر از موجودی است!\n"
                    f"موجودی قابل دسترس: {current_selection['quantity']}\n\n"
                    f"لطفا تعداد معتبر وارد کنید (۱ تا {current_selection['quantity']}):"
                )
                return States.SELECT_QUANTITY
                
        except ValueError:
            await update.message.reply_text(
                "❌ لطفا یک عدد معتبر وارد کنید.\n"
                f"مثال: ۵ یا 10\n\n"
                f"موجودی قابل دسترس: {current_selection['quantity']}"
            )
            return States.SELECT_QUANTITY
        
        # اضافه کردن به لیست مناسب
        list_type = "درخواستی" if current_selection['type'] == 'target' else "جبرانی"
        
        if current_selection['type'] == 'target':
            if 'offer_items' not in context.user_data:
                context.user_data['offer_items'] = []
            
            # 🔥 تغییر اصلی: بررسی تکراری نبودن دارو و جمع کردن مقادیر
            existing_index = None
            for i, item in enumerate(context.user_data['offer_items']):
                if item['drug_id'] == current_selection['id']:
                    existing_index = i
                    break
            
            if existing_index is not None:
                # 🔥 جمع کردن مقدار جدید با مقدار موجود
                new_quantity = context.user_data['offer_items'][existing_index]['quantity'] + quantity
                
                # بررسی عدم превыاز موجودی
                if new_quantity > current_selection['quantity']:
                    await update.message.reply_text(
                        f"❌ جمع تعداد بیشتر از موجودی است!\n"
                        f"موجودی قابل دسترس: {current_selection['quantity']}\n"
                        f"تعداد قبلی: {context.user_data['offer_items'][existing_index]['quantity']}\n"
                        f"تعداد جدید: {quantity}\n\n"
                        f"لطفا تعداد معتبر وارد کنید:"
                    )
                    return States.SELECT_QUANTITY
                
                # به روزرسانی تعداد موجود
                context.user_data['offer_items'][existing_index]['quantity'] = new_quantity
                action = "افزایش یافت"
            else:
                # اضافه کردن آیتم جدید
                context.user_data['offer_items'].append({
                    'drug_id': current_selection['id'],
                    'drug_name': current_selection['name'],
                    'price': current_selection['price'],
                    'quantity': quantity,
                    'pharmacy_id': context.user_data.get('selected_pharmacy_id')
                })
                action = "اضافه شد"
                
        else:
            if 'comp_items' not in context.user_data:
                context.user_data['comp_items'] = []
            
            # 🔥 تغییر اصلی: بررسی تکراری نبودن دارو و جمع کردن مقادیر
            existing_index = None
            for i, item in enumerate(context.user_data['comp_items']):
                if item['id'] == current_selection['id']:
                    existing_index = i
                    break
            
            if existing_index is not None:
                # 🔥 جمع کردن مقدار جدید با مقدار موجود
                new_quantity = context.user_data['comp_items'][existing_index]['quantity'] + quantity
                
                # بررسی عدم превыاز موجودی
                if new_quantity > current_selection['quantity']:
                    await update.message.reply_text(
                        f"❌ جمع تعداد بیشتر از موجودی است!\n"
                        f"موجودی قابل دسترس: {current_selection['quantity']}\n"
                        f"تعداد قبلی: {context.user_data['comp_items'][existing_index]['quantity']}\n"
                        f"تعداد جدید: {quantity}\n\n"
                        f"لطفا تعداد معتبر وارد کنید:"
                    )
                    return States.SELECT_QUANTITY
                
                # به روزرسانی تعداد موجود
                context.user_data['comp_items'][existing_index]['quantity'] = new_quantity
                action = "افزایش یافت"
            else:
                # اضافه کردن آیتم جدید
                context.user_data['comp_items'].append({
                    'id': current_selection['id'],
                    'name': current_selection['name'],
                    'price': current_selection['price'],
                    'quantity': quantity
                })
                action = "اضافه شد"
        
        # محاسبه مجموع‌های به روز شده
        offer_items = context.user_data.get('offer_items', [])
        comp_items = context.user_data.get('comp_items', [])
        
        offer_total = sum(parse_price(item['price']) * item['quantity'] for item in offer_items)
        comp_total = sum(parse_price(item['price']) * item['quantity'] for item in comp_items)
        price_difference = offer_total - comp_total
        
        # ساخت پیام با جزئیات کامل
        message = f"✅ {quantity} عدد از {current_selection['name']} به لیست {list_type} {action}.\n\n"
        
        # نمایش همه داروهای انتخاب شده
        if offer_items:
            message += "📌 داروهای درخواستی:\n"
            for i, item in enumerate(offer_items, 1):
                item_total = parse_price(item['price']) * item['quantity']
                message += f"{i}. {item['drug_name']} - {item['quantity']} عدد = {format_price(item_total)}\n"
        
        if comp_items:
            message += "\n📌 داروهای جبرانی:\n"
            for i, item in enumerate(comp_items, 1):
                item_total = parse_price(item['price']) * item['quantity']
                message += f"{i}. {item['name']} - {item['quantity']} عدد = {format_price(item_total)}\n"
        
        message += f"\n📊 خلاصه فعلی:\n"
        message += f"جمع درخواستی: {format_price(offer_total)}\n"
        message += f"جمع جبرانی: {format_price(comp_total)}\n"
        message += f"اختلاف قیمت: {format_price(price_difference)}\n"
        
        # راهنمای وضعیت اختلاف قیمت
        if price_difference > 0:
            message += f"⚠️ شما باید {format_price(price_difference)} دیگر جبران کنید.\n"
        elif price_difference < 0:
            message += f"✅ شما {format_price(abs(price_difference))} بیشتر جبران کرده‌اید.\n"
        else:
            message += "✅ مبادله متعادل است!\n"
        
        # پاک کردن انتخاب جاری
        context.user_data.pop('current_selection', None)
        
        await update.message.reply_text(
            message,
            reply_markup=ReplyKeyboardRemove()
        )
        
        # بازگشت به لیست داروها با اطلاعات به روز شده
        return await show_two_column_selection(update, context)
        
    except Exception as e:
        logger.error(f"Error in enter_quantity: {e}", exc_info=True)
        
        await update.message.reply_text(
            "❌ خطا در ثبت تعداد!\n\n"
            "در حال بازگشت به لیست داروها...",
            reply_markup=ReplyKeyboardRemove()
        )
        
        # بازگشت به لیست داروها
        return await show_two_column_selection(update, context)

async def select_drug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """انتخاب دارو از لیست"""
    await clear_conversation_state(update, context, silent=True)
    try:
        selection = update.message.text
        user_id = update.effective_user.id
        pharmacy_id = context.user_data.get('selected_pharmacy_id')
        
        # تشخیص نوع لیست (هدف یا کاربر)
        current_list = 'target' if selection.startswith('📌') else 'mine'
        context.user_data['current_list'] = current_list
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                if current_list == 'target':
                    cursor.execute('''
                    SELECT id, name, price, quantity, date
                    FROM drug_items
                    WHERE user_id = %s AND quantity > 0
                    ORDER BY name
                    ''', (pharmacy_id,))
                else:
                    cursor.execute('''
                    SELECT id, name, price, quantity, date
                    FROM drug_items
                    WHERE user_id = %s AND quantity > 0
                    ORDER BY name
                    ''', (user_id,))
                
                drugs = cursor.fetchall()
                
                # پیدا کردن داروی انتخاب شده
                selected_drug = None
                for drug in drugs:
                    expected_text = f"{'📌' if current_list == 'target' else '💊'} {format_button_text(drug['name'], 15)} - {drug['price']}"
                    if expected_text == selection:
                        selected_drug = drug
                        break
                
                if not selected_drug:
                    await update.message.reply_text("دارو یافت نشد.")
                    return States.SELECT_DRUGS
                
                context.user_data['current_selection'] = {
                    'id': selected_drug['id'],
                    'name': selected_drug['name'],
                    'price': selected_drug['price'],
                    'quantity': selected_drug['quantity'],
                    'date': selected_drug['date'],
                    'type': current_list
                }
                
                await update.message.reply_text(
                    f"💊 داروی انتخاب شده: {selected_drug['name']}\n"
                    f"💰 قیمت: {selected_drug['price']}\n"
                    f"📅 تاریخ انقضا: {selected_drug['date']}\n"
                    f"📦 موجودی: {selected_drug['quantity']}\n\n"
                    f"لطفا تعداد مورد نظر را وارد کنید:",
                    reply_markup=ReplyKeyboardRemove()
                )
                return States.SELECT_QUANTITY
                
        except Exception as e:
            logger.error(f"Error in select_drug: {e}")
            await update.message.reply_text("خطا در انتخاب دارو")
        finally:
            if conn:
                conn.close()
                
    except Exception as e:
        logger.error(f"Error in select_drug: {e}")
        await update.message.reply_text("خطایی در انتخاب دارو رخ داد")
    return States.SELECT_DRUGS

async def handle_back_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دکمه بازگشت"""
    await clear_conversation_state(update, context, silent=True)
    try:
        if update.message.text == "🔙 بازگشت به داروخانه‌ها":
            # پاک کردن context مربوط به انتخاب دارو
            keys_to_remove = [
                'selected_pharmacy_id', 'selected_pharmacy_name', 
                'offer_items', 'comp_items', 'current_selection',
                'target_drugs', 'my_drugs', 'target_page', 'my_page'
            ]
            
            for key in keys_to_remove:
                context.user_data.pop(key, None)
            
            await update.message.reply_text(
                "لطفا نام داروی مورد نظر را وارد کنید:",
                reply_markup=ReplyKeyboardRemove()
            )
            
            return States.SEARCH_DRUG
            
    except Exception as e:
        logger.error(f"Error in handle_back_button: {e}")
        await update.message.reply_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
    return States.SELECT_DRUGS

async def handle_finish_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دکمه اتمام انتخاب"""
    await clear_conversation_state(update, context, silent=True)
    try:
        if update.message.text == "✅ اتمام انتخاب":
            return await submit_offer(update, context)
            
    except Exception as e:
        logger.error(f"Error in handle_finish_selection: {e}")
        await update.message.reply_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
    return States.SELECT_DRUGS

async def safe_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    """ارسال ایمن پیام با مدیریت خطاهای مختلف"""
    try:
        if not update:
            logger.error("No update provided to safe_reply")
            return
            
        chat_id = None
        if update.callback_query:
            await update.callback_query.answer()
            chat_id = update.callback_query.message.chat_id
        elif update.message:
            chat_id = update.message.chat_id
        elif update.effective_chat:
            chat_id = update.effective_chat.id
        else:
            logger.error("No valid chat ID found in update")
            return
            
        # ارسال پیام
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in safe_reply: {e}")
        # تلاش برای ارسال پیام خطا در صورت امکان
        try:
            if chat_id:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ خطایی در ارسال پیام رخ داد. لطفا دوباره تلاش کنید."
                )
        except Exception as inner_e:
            logger.error(f"Failed to send error message: {inner_e}")
                
    
async def handle_compensation_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle selection of compensation drugs"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()

        if query.data == "compensate":
            # Switch to showing user's drugs for compensation selection
            context.user_data['current_list'] = 'mine'
            return await show_two_column_selection(update, context)
        
        elif query.data.startswith("comp_"):
            # Handle selection of a specific drug for compensation
            drug_id = int(query.data.split("_")[1])
            
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                    cursor.execute('''
                    SELECT id, name, price, quantity
                    FROM drug_items
                    WHERE id = %s AND user_id = %s AND quantity > 0
                    ''', (drug_id, update.effective_user.id))
                    drug = cursor.fetchone()
                    
                    if not drug:
                        await query.edit_message_text("دارو یافت نشد.")
                        return States.COMPENSATION_SELECTION
                    
                    context.user_data['current_comp_drug'] = dict(drug)
                    await query.edit_message_text(
                        f"💊 داروی انتخاب شده: {drug['name']}\n"
                        f"💰 قیمت: {drug['price']}\n"
                        f"📦 موجودی: {drug['quantity']}\n\n"
                        "لطفا تعداد مورد نظر را وارد کنید:"
                    )
                    return States.COMPENSATION_QUANTITY
                    
            except Exception as e:
                logger.error(f"Error in compensation selection: {e}")
                await query.edit_message_text("خطا در انتخاب داروی جبرانی.")
            finally:
                if conn:
                    conn.close()
        
    except Exception as e:
        logger.error(f"Error in handle_compensation_selection: {e}")
        await query.edit_message_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
    return States.COMPENSATION_SELECTION
async def save_compensation_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save quantity for compensation drug"""
    await clear_conversation_state(update, context, silent=True)
    try:
        quantity = update.message.text.strip()
        current_drug = context.user_data.get('current_comp_drug')
        
        if not current_drug:
            await update.message.reply_text("انتخاب دارو از دست رفته. لطفا دوباره شروع کنید.")
            return States.COMPENSATION_SELECTION
            
        try:
            quantity = int(quantity)
            if quantity <= 0 or quantity > current_drug['quantity']:
                await update.message.reply_text(
                    f"لطفا عددی بین 1 و {current_drug['quantity']} وارد کنید."
                )
                return States.COMPENSATION_QUANTITY
        except ValueError:
            await update.message.reply_text("لطفا یک عدد معتبر وارد کنید.")
            return States.COMPENSATION_QUANTITY
        
        # Add to compensation items
        if 'comp_items' not in context.user_data:
            context.user_data['comp_items'] = []
            
        context.user_data['comp_items'].append({
            'id': current_drug['id'],
            'name': current_drug['name'],
            'price': current_drug['price'],
            'quantity': quantity
        })
        
        await update.message.reply_text(
            f"تعداد {quantity} برای {current_drug['name']} به عنوان جبران ثبت شد."
        )
        return await submit_offer(update, context)
        
    except Exception as e:
        logger.error(f"Error in save_compensation_quantity: {e}")
        await update.message.reply_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
    return States.COMPENSATION_SELECTION
async def confirm_totals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show final totals before sending offer"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()
        
        offer_items = context.user_data.get('offer_items', [])
        comp_items = context.user_data.get('comp_items', [])
        
        if not offer_items:
            await query.edit_message_text("هیچ دارویی برای ارسال وجود ندارد.")
            return States.SELECT_DRUGS
            
        offer_total = sum(parse_price(item['price']) * item['quantity'] for item in offer_items)
        comp_total = sum(parse_price(item['price']) * item['quantity'] for item in comp_items)
        
        keyboard = [
            [InlineKeyboardButton("✅ ارسال پیشنهاد", callback_data="send_offer")],
            [InlineKeyboardButton("✏️ ویرایش", callback_data="edit_selection")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_selection")]
        ]
        
        message = "📋 تأیید نهایی پیشنهاد:\n\n"
        message += "📌 داروهای درخواستی:\n"
        for item in offer_items:
            message += f"- {item['drug_name']} ({item['quantity']} عدد) - {item['price']}\n"
        message += f"\n💰 جمع کل درخواستی: {format_price(offer_total)}\n"
        
        message += "\n📌 داروهای جبرانی شما:\n"
        if comp_items:
            for item in comp_items:
                message += f"- {item['name']} ({item['quantity']} عدد) - {item['price']}\n"
            message += f"\n💰 جمع کل جبرانی: {format_price(comp_total)}\n"
        else:
            message += "هیچ داروی جبرانی انتخاب نشده است.\n"
        
        message += f"\n📊 اختلاف قیمت: {format_price(offer_total - comp_total)}\n"
        message += "\nآیا از ارسال این پیشنهاد مطمئن هستید؟"
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.CONFIRM_TOTALS
    except Exception as e:
        logger.error(f"Error in confirm_totals: {e}")
        await query.edit_message_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
    return States.COMPENSATION_SELECTION

async def submit_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show selected drugs and compensation items with price difference"""
    await clear_conversation_state(update, context, silent=True)
    try:
        if not update.message:
            logger.error("No message in update")
            return States.SELECT_DRUGS
            
        offer_items = context.user_data.get('offer_items', [])
        comp_items = context.user_data.get('comp_items', [])
        
        if not offer_items:
            await update.message.reply_text(
                "هیچ دارویی از داروخانه انتخاب نشده است.",
                reply_markup=ReplyKeyboardRemove()
            )
            # بازگشت به لیست انتخاب دارو
            return await show_two_column_selection(update, context)
        
        offer_total = sum(parse_price(item['price']) * item['quantity'] for item in offer_items)
        comp_total = sum(parse_price(item['price']) * item['quantity'] for item in comp_items)
        price_difference = offer_total - comp_total
        
        message = "📋 خلاصه پیشنهاد:\n\n"
        message += "📌 داروهای درخواستی:\n"
        for item in offer_items:
            message += f"- {item['drug_name']} ({item['quantity']} عدد) - {item['price']}\n"
        message += f"\n💰 جمع کل درخواستی: {format_price(offer_total)}\n"
        
        message += "\n📌 داروهای جبرانی شما:\n"
        if comp_items:
            for item in offer_items:
              message += f"- {item['drug_name']} - {item['price']}\n"
              message += f"  📦 تعداد: {item['quantity']} عدد | 📅 تاریخ: {item.get('date', 'نامشخص')}\n"
            message += f"\n💰 جمع کل جبرانی: {format_price(comp_total)}\n"
        else:
            message += "هیچ داروی جبرانی انتخاب نشده است.\n"
        
        message += f"\n📊 اختلاف قیمت: {format_price(price_difference)}\n"
        if price_difference > 0:
            message += "⚠️ شما باید داروهای جبرانی بیشتری انتخاب کنید تا اختلاف قیمت صفر یا منفی شود.\n"
        
        keyboard = []
        if price_difference > 0:
            keyboard.append([InlineKeyboardButton("➕ افزودن داروی جبرانی", callback_data="add_more")])
        keyboard.append([InlineKeyboardButton("✅ تأیید و ارسال", callback_data="confirm_offer")])
        keyboard.append([InlineKeyboardButton("✏️ ویرایش انتخاب‌ها", callback_data="edit_selection")])
        #keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_selection")])
        
        if price_difference > 0:
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                    # ابتدا همه داروها را بگیرید
                    cursor.execute('''
                    SELECT di.id, di.name, di.price, di.quantity
                    FROM drug_items di
                    WHERE di.user_id = %s AND di.quantity > 0
                    ''', (update.effective_user.id,))
                    all_drugs = cursor.fetchall()
                    
                    # در پایتون بر اساس قیمت عددی مرتب کنید
                    all_drugs.sort(key=lambda x: parse_price(x['price']), reverse=True)
                    suggested_drugs = all_drugs[:3]  # 3 مورد اول
                    
                    if suggested_drugs:
                        message += "\n📜 پیشنهاد داروهای جبرانی:\n"
                        for drug in suggested_drugs:
                            message += f"- {item['name']} - {item['price']}\n"
                            message += f"  📦 تعداد: {item['quantity']} عدد | 📅 تاریخ: {item.get('date', 'نامشخص')}\n"
            except Exception as e:
                logger.error(f"Error suggesting compensation drugs: {e}")
            finally:
                if conn:
                    conn.close()
        
        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.CONFIRM_OFFER
        
    except Exception as e:
        logger.error(f"Error in submit_offer: {e}")
        if update.message:
            await update.message.reply_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END


async def confirm_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm the offer before sending"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()
        
        offer_items = context.user_data.get('offer_items', [])
        comp_items = context.user_data.get('comp_items', [])
        
        if not offer_items:
            await query.edit_message_text("هیچ دارویی برای ارسال وجود ندارد.")
            return States.SELECT_DRUGS
            
        offer_total = sum(parse_price(item['price']) * item['quantity'] for item in offer_items)
        comp_total = sum(parse_price(item['price']) * item['quantity'] for item in comp_items)
        
        if offer_total > comp_total:
            await query.edit_message_text(
                "⚠️ اختلاف قیمت مثبت است. لطفا داروهای جبرانی بیشتری انتخاب کنید."
            )
            return await submit_offer(update, context)
        
        keyboard = [
            [InlineKeyboardButton("✅ ارسال پیشنهاد", callback_data="send_offer")],
            [InlineKeyboardButton("✏️ ویرایش", callback_data="edit_selection")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_selection")]
        ]
        
        message = "📋 تأیید نهایی پیشنهاد:\n\n"
        message += "📌 داروهای درخواستی:\n"
        for item in offer_items:
            message += f"- {item['drug_name']} - {item['price']}\n"
            message += f"  📦 تعداد: {item['quantity']} عدد | 📅 تاریخ: {item.get('date', 'نامشخص')}\n"
        message += f"\n💰 جمع کل درخواستی: {format_price(offer_total)}\n"
        
        message += "\n📌 داروهای جبرانی شما:\n"
        if comp_items:
            for item in comp_items:
                # استفاده از get برای مدیریت فیلدهای ممکن
                drug_name = item.get('name') or item.get('drug_name', 'نامشخص')
                price = item.get('price', 'نامشخص')
                quantity = item.get('quantity', 0)
                date = item.get('date', 'نامشخص')
                
                message += f"- {drug_name} - {price}\n"
                message += f"  📦 تعداد: {quantity} عدد | 📅 تاریخ: {date}\n"
            message += f"\n💰 جمع کل جبرانی: {format_price(comp_total)}\n"
        else:
            message += "هیچ داروی جبرانی انتخاب نشده است.\n"
        
        message += f"\n📊 اختلاف قیمت: {format_price(offer_total - comp_total)}\n"
        message += "\nآیا از ارسال این پیشنهاد مطمئن هستید؟"
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.CONFIRM_OFFER
    except Exception as e:
        logger.error(f"Error in confirm_offer: {e}")
        await query.edit_message_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
async def send_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the finalized offer to the pharmacy"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()
        
        offer_items = context.user_data.get('offer_items', [])
        comp_items = context.user_data.get('comp_items', [])
        
        if not offer_items:
            await query.edit_message_text("هیچ دارویی برای ارسال وجود ندارد.")
            return States.SELECT_DRUGS
            
        pharmacy_id = offer_items[0]['pharmacy_id']
        buyer_id = update.effective_user.id
        offer_total = sum(parse_price(item['price']) * item['quantity'] for item in offer_items)
        comp_total = sum(parse_price(item['price']) * item['quantity'] for item in comp_items)
        
        if offer_total > comp_total:
            await query.edit_message_text(
                "⚠️ اختلاف قیمت مثبت است. لطفا داروهای جبرانی بیشتری انتخاب کنید."
            )
            return await submit_offer(update, context)
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                INSERT INTO offers (pharmacy_id, buyer_id, total_price)
                VALUES (%s, %s, %s)
                RETURNING id
                ''', (pharmacy_id, buyer_id, offer_total))
                offer_id = cursor.fetchone()[0]
                
                for item in offer_items:
                    cursor.execute('''
                    INSERT INTO offer_items (offer_id, drug_name, price, quantity)
                    VALUES (%s, %s, %s, %s)
                    ''', (offer_id, item['drug_name'], item['price'], item['quantity']))
                
                for item in comp_items:
                    cursor.execute('''
                    INSERT INTO compensation_items (offer_id, drug_id, quantity)
                    VALUES (%s, %s, %s)
                    ''', (offer_id, item['id'], item['quantity']))
                
                conn.commit()
                
                keyboard = [
                    [InlineKeyboardButton("✅ تأیید پیشنهاد", callback_data=f"accept_{offer_id}")],
                    [InlineKeyboardButton("❌ رد پیشنهاد", callback_data=f"reject_{offer_id}")]
                ]
                
                offer_message = "📬 پیشنهاد جدید دریافت شد:\n\n"
                offer_message += "📌 داروهای درخواستی:\n"
                for item in offer_items:
                    offer_message += f"- {item['drug_name']} - {item['price']}\n"
                    offer_message += f"  📦 تعداد: {item['quantity']} عدد | 📅 تاریخ: {item.get('date', 'نامشخص')}\n"
                offer_message += f"\n💰 جمع کل درخواستی: {format_price(offer_total)}\n"
                
                offer_message += "\n📌 داروهای جبرانی:\n"
                if comp_items:
                    for item in comp_items:
                        drug_name = item.get('name') or item.get('drug_name', 'نامشخص')
                        price = item.get('price', 'نامشخص')
                        quantity = item.get('quantity', 0)
                        date = item.get('date', 'نامشخص')
                        
                        offer_message += f"- {drug_name} - {price}\n"
                        offer_message += f"  📦 تعداد: {quantity} عدد | 📅 تاریخ: {date}\n"
                    offer_message += f"\n💰 جمع کل جبرانی: {format_price(comp_total)}\n"
                else:
                    offer_message += "هیچ داروی جبرانی انتخاب نشده است.\n"
                
                offer_message += f"\n📊 اختلاف قیمت: {format_price(offer_total - comp_total)}\n"
                
                await context.bot.send_message(
                    chat_id=pharmacy_id,
                    text=offer_message,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                await query.edit_message_text(
                    "✅ پیشنهاد شما با موفقیت ارسال شد!\n\n"
                    "پس از تأیید داروخانه با شما تماس گرفته خواهد شد."
                )
                
                # نمایش منوی اصلی بعد از ارسال موفقیت‌آمیز
                keyboard = [
                    ['اضافه کردن دارو', 'جستجوی دارو'],
                    ['تنظیم شاخه‌های دارویی', 'لیست داروهای من'],
                    ['ثبت نیاز جدید', 'لیست نیازهای من']
                ]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="به منوی اصلی بازگشتید:",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error saving offer: {e}")
            if conn:
                conn.rollback()
            await query.edit_message_text("خطا در ثبت پیشنهاد. لطفا دوباره تلاش کنید.")
        finally:
            if conn:
                conn.close()
        
        context.user_data.clear()
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in send_offer: {e}")
        await query.edit_message_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def handle_back_to_pharmacies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle back to pharmacy selection"""
    await clear_conversation_state(update, context, silent=True)
    try:
        # پاک کردن کامل context مربوط به انتخاب دارو
        keys_to_remove = [
            'selected_pharmacy_id', 'selected_pharmacy_name', 
            'offer_items', 'comp_items', 'current_selection',
            'current_list', 'page_target', 'page_mine'
        ]
        
        for key in keys_to_remove:
            context.user_data.pop(key, None)
        
        keyboard = [[InlineKeyboardButton("🔍 جستجوی مجدد", switch_inline_query_current_chat="")]]
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "برای انتخاب داروخانه دیگر، دکمه زیر را کلیک کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                "برای انتخاب داروخانه دیگر، دکمه زیر را کلیک کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return States.SEARCH_DRUG
            
    except Exception as e:
        logger.error(f"Error in handle_back_to_pharmacies: {e}")
        error_msg = "خطایی رخ داد. لطفا دوباره تلاش کنید."
        if update.callback_query:
            await update.callback_query.edit_message_text(error_msg)
        else:
            await update.message.reply_text(error_msg)
        return ConversationHandler.END
async def handle_match_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle match notification and initiate exchange"""
    
    try:
        query = update.callback_query
        await query.answer()
        
        data = query.data.split('_')
        drug_id = int(data[2])
        need_id = int(data[3])
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT di.id, di.name, di.price, di.quantity, di.date,
                       u.id as pharmacy_id, p.name as pharmacy_name
                FROM drug_items di
                JOIN users u ON di.user_id = u.id
                JOIN pharmacies p ON u.id = p.user_id
                WHERE di.id = %s
                ''', (drug_id,))
                drug = cursor.fetchone()
                
                cursor.execute('''
                SELECT id, name, quantity
                FROM user_needs 
                WHERE id = %s AND user_id = %s
                ''', (need_id, update.effective_user.id))
                need = cursor.fetchone()
                
                if not drug or not need:
                    await query.edit_message_text("اطلاعات یافت نشد.")
                    return ConversationHandler.END
                
                context.user_data['match_drug'] = dict(drug)
                context.user_data['match_need'] = dict(need)
                
                keyboard = [
                    [InlineKeyboardButton("💊 مبادله این دارو", callback_data=f"exchange_{drug_id}")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
                ]
                
                await query.edit_message_text(
                    f"💊 داروی مطابق نیاز:\n\n"
                    f"🏥 داروخانه: {drug['pharmacy_name']}\n"
                    f"🔹 دارو: {drug['name']}\n"
                    f"💰 قیمت: {format_button_text(drug['price'], max_length=40)}\n"
                    f"📅 تاریخ انقضا: {drug['date']}\n"
                    f"📦 موجودی: {drug['quantity']}\n\n"
                    f"📝 نیاز شما:\n"
                    f"🔹 دارو: {need['name']}\n"
                    f"📦 تعداد مورد نیاز: {need['quantity']}\n\n"
                    "آیا مایل به مبادله هستید؟",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return States.SELECT_DRUGS
        except Exception as e:
            logger.error(f"Error handling match: {e}")
            await query.edit_message_text("خطا در دریافت اطلاعات تطابق.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in handle_match_notification: {e}")
        await query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation and return to main menu"""
    try:
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("عملیات لغو شد.")
        elif update.message:
            await update.message.reply_text("عملیات لغو شد.")
        
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['تنظیم شاخه‌های دارویی', 'لیست داروهای من'],
            ['ثبت نیاز جدید', 'لیست نیازهای من']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="به منوی اصلی بازگشتید. لطفا یک گزینه را انتخاب کنید:",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in cancel: {e}")
        return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.error(
            msg="Exception while handling update:",
            exc_info=context.error,
            extra={
                'update': update.to_dict() if update else None,
                'user_data': context.user_data,
                'state': context.user_data.get('state', 'unknown')
            }
        )
        
        error_message = (
            "⚠️ خطایی در پردازش درخواست شما رخ داد.\n"
            "لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
        )
        
        # ارسال پیام خطا به صورت ایمن
        try:
            if update and update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=error_message
                )
                await clear_conversation_state(update, context, silent=True)
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")
        
        # Notify admin
        tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
        tb_string = ''.join(tb_list)
        admin_message = (
            f"⚠️ خطا برای کاربر {update.effective_user.id if update and update.effective_user else 'unknown'}:\n\n"
            f"{context.error}\n\n"
            f"Traceback:\n<code>{html.escape(tb_string)}</code>\n\n"
            f"User Data: {context.user_data}"
        )
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_message,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error in error handler: {e}")
async def main_menu_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دسترسی به منوی اصلی از هر جای ربات"""
    try:
        # ایجاد کیبورد منوی اصلی
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "به منوی اصلی بازگشتید. لطفاً یک گزینه را انتخاب کنید:",
            reply_markup=reply_markup
        )
        
        # پاک کردن state فعلی
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in main_menu_access: {e}")
        await update.message.reply_text("خطایی در بازگشت به منوی اصلی رخ داد.")
        return ConversationHandler.END

async def handle_state_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت تغییر فاز بین عملیات مختلف با تشخیص stateهای فعال"""
    try:
        text = update.message.text.strip()
        logger.info(f"State change requested: {text}")

        # 🔥 پاک‌سازی کامل state قبل از تغییر منو
        context.user_data.clear()

        # بررسی stateهای فعال که نیاز به ورود داده دارند
        input_states = [
            States.ADD_DRUG_DATE,
            States.ADD_DRUG_QUANTITY,
            States.ADD_NEED_QUANTITY,
            States.SELECT_QUANTITY,
            States.EDIT_DRUG,
            States.EDIT_NEED,
            States.SEARCH_DRUG_FOR_ADDING,
            States.ADD_DRUG_FROM_INLINE,
            States.SEARCH_DRUG_FOR_NEED,
            States.REGISTER_PHARMACY_NAME,
            States.REGISTER_FOUNDER_NAME,
            States.REGISTER_NATIONAL_CARD,
            States.REGISTER_LICENSE,
            States.REGISTER_MEDICAL_CARD,
            States.REGISTER_PHONE,
            States.REGISTER_ADDRESS,
            States.SIMPLE_VERIFICATION,
            States.PERSONNEL_LOGIN,
            States.SEARCH_DRUG
        ]
        
        current_state = context.user_data.get('_conversation_state')
        
        # اگر در حالتی هستیم که نیاز به ورود داده دارد، state را کاملاً پاک کنیم
        if current_state in input_states:
            # پاک کردن کامل state و بازگشت به منوی اصلی
            context.user_data.clear()
            
            keyboard = [
                ['اضافه کردن دارو', 'جستجوی دارو'],
                ['لیست داروهای من', 'ثبت نیاز جدید'],
                ['لیست نیازهای من', 'ساخت کد پرسنل'],
                ['تنظیم شاخه‌های دارویی']
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                "⚠️ عملیات قبلی لغو شد.\n\nبه منوی اصلی بازگشتید. لطفاً یک گزینه را انتخاب کنید:",
                reply_markup=reply_markup
            )
            return ConversationHandler.END

        # 🔥 پاک‌سازی state قبل از شروع عملیات جدید
        context.user_data.clear()

        # NOTE:
        # Do NOT return the result of called conversation-entry handlers.
        # Returning another ConversationHandler state from this handler causes
        # "PTBUserWarning: 'handle_state_change' returned state ... which is unknown to the ConversationHandler."
        # Instead we call the target handler to send messages and then always
        # return ConversationHandler.END so the current conversation ends cleanly.
        #
        # This ensures the target ConversationHandler's own entry-points / states
        # will be used for subsequent messages instead of the current ConversationHandler,
        # avoiding the "unknown state" issue and the symptom you observed
        # (search stops responding after menu switches).

        if text == 'لیست داروهای من':
            await list_my_drugs(update, context)
            return ConversationHandler.END
        elif text == 'لیست نیازهای من':
            await list_my_needs(update, context)
            return ConversationHandler.END
        elif text == 'اضافه کردن دارو':
            await add_drug_item(update, context)
            return ConversationHandler.END
        elif text == 'ثبت نیاز جدید':
            await add_need(update, context)
            return ConversationHandler.END
        elif text == 'جستجوی دارو':
            await search_drug(update, context)
            return ConversationHandler.END
        elif text == 'ساخت کد پرسنل':
            await generate_personnel_code(update, context)
            return ConversationHandler.END
        elif text == 'تنظیم شاخه‌های دارویی':
            await setup_medical_categories(update, context)
            return ConversationHandler.END
        
        # 🔥 سیستم ویرایش داروها - کاملاً مشابه نیازها
        elif text == '✏️ ویرایش داروها':
            await edit_drugs(update, context)
            return ConversationHandler.END
        elif text.startswith('✏️ ') and not text.endswith('ها'):
            # تشخیص دکمه‌های ویرایش داروهای خاص (مثل "✏️ استامینوفن")
            await handle_select_drug_for_edit(update, context)
            return ConversationHandler.END

        elif text in ['✏️ ویرایش تاریخ', '✏️ ویرایش تعداد', '🗑️ حذف دارو']:
            # مدیریت دکمه‌های ویرایش جزئیات دارو
            await handle_drug_edit_action_from_keyboard(update, context)
            return ConversationHandler.END
        elif text in ['✅ بله، حذف شود', '❌ خیر، انصراف'] and 'editing_drug' in context.user_data:
            # مدیریت تأیید حذف دارو
            await handle_drug_deletion_confirmation(update, context)
            return ConversationHandler.END
        elif text == '🔙 بازگشت به لیست داروها':
            # بازگشت از ویرایش جزئیات به لیست داروها
            await list_my_drugs(update, context)
            return ConversationHandler.END
        
        # 🔥 سیستم ویرایش نیازها
        elif text == '✏️ ویرایش نیازها':
            await handle_edit_needs_button(update, context)
            return ConversationHandler.END
        elif text.startswith('✏️ ') and ' (' in text and text.endswith(')'):
            # تشخیص دکمه‌های ویرایش نیازهای خاص (مثل "✏️ استامینوفن (100)")
            await handle_select_need_for_edit(update, context)
            return ConversationHandler.END
        elif text in ['✏️ ویرایش نام', '✏️ ویرایش توضیحات', '✏️ ویرایش تعداد', '🗑️ حذف نیاز']:
            # مدیریت دکمه‌های ویرایش جزئیات نیاز
            await handle_need_edit_action_from_keyboard(update, context)
            return ConversationHandler.END
        elif text in ['✅ بله، حذف شود', '❌ خیر، انصراف'] and 'editing_need' in context.user_data:
            # مدیریت تأیید حذف نیاز
            await handle_need_deletion_confirmation(update, context)
            return ConversationHandler.END
        elif text == '🔙 بازگشت به لیست نیازها':
            # بازگشت از ویرایش جزئیات به لیست نیازها
            await list_my_needs(update, context)
            return ConversationHandler.END
        
        # 🔥 بازگشت‌های عمومی
        elif text == '🔙 بازگشت به منوی اصلی':
            # بازگشت به منوی اصلی
            keyboard = [
                ['اضافه کردن دارو', 'جستجوی دارو'],
                ['لیست داروهای من', 'ثبت نیاز جدید'],
                ['لیست نیازهای من', 'ساخت کد پرسنل'],
                ['تنظیم شاخه‌های دارویی']
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "به منوی اصلی بازگشتید. لطفاً یک گزینه را انتخاب کنید:",
                reply_markup=reply_markup
            )
            return ConversationHandler.END
        elif text == '🔙 بازگشت':
            # بازگشت عمومی - تشخیص نوع بازگشت بر اساس context
            if 'editing_drug' in context.user_data or 'editing_drugs_list' in context.user_data:
                await list_my_drugs(update, context)
                return ConversationHandler.END
            elif 'editing_need' in context.user_data or 'user_needs_list' in context.user_data:
                await list_my_needs(update, context)
                return ConversationHandler.END
            else:
                # بازگشت به منوی اصلی اگر context مشخص نیست
                await clear_conversation_state(update, context)
                return ConversationHandler.END
        
        else:
            keyboard = [
                ['اضافه کردن دارو', 'جستجوی دارو'],
                ['لیست داروهای من', 'ثبت نیاز جدید'],
                ['لیست نیازهای من', 'ساخت کد پرسنل'],
                ['تنظیم شاخه‌های دارویی']
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "لطفاً یک گزینه معتبر از منوی اصلی انتخاب کنید:",
                reply_markup=reply_markup
            )
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"Error in handle_state_change: {e}", exc_info=True)
        await update.message.reply_text("خطایی در تغییر حالت رخ داد. لطفا دوباره تلاش کنید.")
        
        # پاک‌سازی کامل در صورت خطا
        context.user_data.clear()
        
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "به منوی اصلی بازگشتید:",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
            
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اخراج کاربر توسط ادمین"""
    try:
        # بررسی اینکه update دارای message است
        if not update.message:
            logger.error("No message in update for ban_user")
            return
        
        # بررسی اینکه کاربر ادمین است
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('SELECT is_admin FROM users WHERE id = %s', (update.effective_user.id,))
                result = cursor.fetchone()
                
                if not result or not result[0]:
                    await update.message.reply_text("❌ شما مجوز انجام این کار را ندارید.")
                    return
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
            await update.message.reply_text("خطا در بررسی مجوزها.")
            return
        finally:
            if conn:
                conn.close()
        
        # بررسی اینکه آیدی کاربر وارد شده است
        if not context.args:
            await update.message.reply_text("❌ لطفا آیدی کاربر را وارد کنید:\n/ban_user <user_id>")
            return
        
        try:
            user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ آیدی کاربر باید عدد باشد.")
            return
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # بررسی وجود کاربر
                cursor.execute('SELECT id, is_verified FROM users WHERE id = %s', (user_id,))
                user_data = cursor.fetchone()
                
                if not user_data:
                    await update.message.reply_text(f"❌ کاربر با آیدی {user_id} یافت نشد.")
                    return
                
                # غیرفعال کردن کاربر (حذف وضعیت تایید و نقش‌ها)
                cursor.execute('''
                UPDATE users 
                SET is_verified = FALSE,
                    is_pharmacy_admin = FALSE,
                    is_personnel = FALSE,
                    verification_method = NULL,
                    simple_code = NULL,
                    creator_id = NULL
                WHERE id = %s
                RETURNING id
                ''', (user_id,))
                
                # همچنین وضعیت داروخانه را غیرفعال کنیم (اما اطلاعاتش باقی بماند)
                cursor.execute('''
                UPDATE pharmacies 
                SET verified = FALSE,
                    verified_at = NULL,
                    admin_id = NULL
                WHERE user_id = %s
                ''', (user_id,))
                
                conn.commit()
                
                # ارسال پیام به کاربر مبنی بر اخراج با حذف کیبورد
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="❌ حساب شما توسط ادمین اخراج شد.\n\n"
                             "برای استفاده مجدد از ربات، لطفا دوباره ثبت‌نام کنید.",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    
                    # ارسال دکمه شروع مجدد
                    keyboard = [
                        [InlineKeyboardButton("🔄 شروع مجدد", callback_data="restart_after_ban")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="برای شروع مجدد و ثبت‌نام دوباره روی دکمه زیر کلیک کنید:",
                        reply_markup=reply_markup
                    )
                    
                except Exception as e:
                    logger.error(f"Failed to notify banned user: {e}")
                
                await update.message.reply_text(
                    f"✅ کاربر {user_id} با موفقیت اخراج شد.\n"
                    f"اطلاعات کاربر در سیستم باقی مانده و می‌تواند دوباره ثبت‌نام کند."
                )
                
        except Exception as e:
            logger.error(f"Error banning user {user_id}: {e}")
            if conn:
                conn.rollback()
            await update.message.reply_text("خطا در اخراج کاربر.")
        finally:
            if conn:
                conn.close()
                
    except Exception as e:
        logger.error(f"Error in ban_user: {e}")
        # استفاده از روش ایمن برای ارسال پیام خطا
        try:
            if update and update.message:
                await update.message.reply_text("خطایی در پردازش درخواست رخ داد.")
            elif update and update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="خطایی در پردازش درخواست رخ داد."
                )
        except Exception as send_error:
            logger.error(f"Failed to send error message: {send_error}")
async def handle_restart_after_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle restart for banned users"""
    try:
        query = update.callback_query
        if query:
            await query.answer()
            user_id = query.from_user.id
            chat_id = query.message.chat_id
        else:
            user_id = update.effective_user.id
            chat_id = update.effective_chat.id
        
        # بررسی اینکه کاربر واقعاً اخراج شده است
        conn = None
        is_banned = False
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('SELECT is_verified FROM users WHERE id = %s', (user_id,))
                result = cursor.fetchone()
                
                if result and not result[0]:  # اگر کاربر تایید نشده باشد (اخراج شده)
                    is_banned = True
                    
        except Exception as e:
            logger.error(f"Error checking user status: {e}")
        finally:
            if conn:
                conn.close()
        
        if not is_banned:
            # اگر کاربر اخراج نشده، به منوی اصلی برود
            return await start(update, context)
        
        # نمایش گزینه‌های ثبت‌نام برای کاربر اخراج شده
        keyboard = [
            [InlineKeyboardButton("ثبت نام با تایید ادمین", callback_data="admin_verify")],
            [InlineKeyboardButton("ورود با کد پرسنل", callback_data="personnel_login")],
            [InlineKeyboardButton("ثبت نام با مدارک", callback_data="register")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = (
            "❌ حساب شما اخراج شده است.\n\n"
            "برای استفاده مجدد از ربات، لطفا یکی از روش‌های زیر را انتخاب کنید:"
        )
        
        if query:
            try:
                await query.edit_message_text(
                    message_text,
                    reply_markup=reply_markup
                )
            except:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message_text,
                    reply_markup=reply_markup
                )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message_text,
                reply_markup=reply_markup
            )
        
        return States.START
        
    except Exception as e:
        logger.error(f"Error in handle_restart_after_ban: {e}")
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="خطایی در پردازش درخواست رخ داد."
            )
        except:
            pass
        return ConversationHandler.END
def main():
    """Start the bot"""
    try:
        # Initialize database
        asyncio.get_event_loop().run_until_complete(initialize_db())
        
        # Load drug data
        if not load_drug_data():
            logger.warning("Failed to load drug data - some features may not work")
        
        # Create application with persistence
        persistence = PicklePersistence(filepath='bot_data.pickle')
        application = ApplicationBuilder().token("8447101535:AAFMFkqJeMFNBfhzrY1VURkfJI-vu766LrY").persistence(persistence).build()
        
        # تعریف توابع کمکی برای نمایش خطا
        async def ask_for_national_card_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """درخواست مجدد عکس کارت ملی"""
            await update.message.reply_text("❌ لطفا فقط تصویر کارت ملی را ارسال کنید.")
            return States.REGISTER_NATIONAL_CARD

        async def ask_for_license_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """درخواست مجدد عکس پروانه داروخانه"""
            await update.message.reply_text("❌ لطفا فقط تصویر پروانه داروخانه را ارسال کنید.")
            return States.REGISTER_LICENSE

        async def ask_for_medical_card_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """درخواست مجدد عکس کارت نظام پزشکی"""
            await update.message.reply_text("❌ لطفا فقط تصویر کارت نظام پزشکی را ارسال کنید.")
            return States.REGISTER_MEDICAL_CARD

        async def ask_for_phone_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """درخواست مجدد شماره تلفن"""
            keyboard = ReplyKeyboardMarkup(
                [[KeyboardButton("📞 اشتراک گذاری شماره تلفن", request_contact=True)]],
                resize_keyboard=True,
                one_time_keyboard=True
            )
            await update.message.reply_text(
                "❌ لطفا از دکمه اشتراک گذاری شماره تلفن استفاده کنید:",
                reply_markup=keyboard
            )
            return States.REGISTER_PHONE

        # فیلترهای دقیق‌تر برای تشخیص پیام‌های غیرمجاز
        non_photo_filter = filters.ALL & ~filters.COMMAND & ~filters.PHOTO & ~filters.Document.IMAGE
        non_contact_filter = filters.ALL & ~filters.COMMAND & ~filters.CONTACT

        # Admin verification handler
        admin_verify_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(admin_verify_start, pattern="^admin_verify$")
            ],
            states={
                States.ADMIN_VERIFY_PHARMACY_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_verify_pharmacy_name)
                ],
                States.REGISTER_PHONE: [
                    MessageHandler(filters.ALL & ~filters.COMMAND, receive_phone_for_admin_verify)
                
                ]
            },
            fallbacks=[CommandHandler('cancel', clear_conversation_state)],
            allow_reentry=True
        )
        
        # Registration handler (normal registration) - کاملا اصلاح شده
        registration_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(register_pharmacy_name, pattern="^register$")
            ],
            states={
                States.REGISTER_PHARMACY_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, register_founder_name)
                ],
                States.REGISTER_FOUNDER_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, register_national_card)
                ],
                States.REGISTER_NATIONAL_CARD: [
                    MessageHandler(filters.PHOTO | filters.Document.IMAGE, register_license),
                    MessageHandler(non_photo_filter, ask_for_national_card_photo)
                ],
                States.REGISTER_LICENSE: [
                    MessageHandler(filters.PHOTO | filters.Document.IMAGE, register_medical_card),
                    MessageHandler(non_photo_filter, ask_for_license_photo)
                ],
                States.REGISTER_MEDICAL_CARD: [
                    MessageHandler(filters.PHOTO | filters.Document.IMAGE, register_phone),
                    MessageHandler(non_photo_filter, ask_for_medical_card_photo)
                ],
                States.REGISTER_PHONE: [
                    MessageHandler(filters.CONTACT, register_phone),
                    MessageHandler(non_contact_filter, ask_for_phone_contact)
                ],
                States.REGISTER_ADDRESS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, register_address)
                ]
           },
           fallbacks=[CommandHandler('cancel', clear_conversation_state)], 
           allow_reentry=True
)

        # Simple verification handler
        simple_verify_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(simple_verify_start, pattern="^simple_verify$")
            ],
            states={
                States.SIMPLE_VERIFICATION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, simple_verify_code)
                ]
            },
            fallbacks=[CommandHandler('cancel', clear_conversation_state)], 
            allow_reentry=True
        )
        
        # Personnel login handler
        personnel_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(personnel_login_start, pattern="^personnel_login$")
            ],
            states={
                States.PERSONNEL_LOGIN: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, verify_personnel_code)
                ]
            },
            fallbacks=[
                CommandHandler('cancel', lambda u, c: clear_conversation_state(u, c, silent=True)),
                MessageHandler(filters.Regex(r'^(جستجوی دارو|لیست داروهای من|ثبت نیاز جدید|لیست نیازهای من|ساخت کد پرسنل|تنظیم شاخه‌های دارویی)$'), 
                     handle_state_change),
                CallbackQueryHandler(lambda u, c: clear_conversation_state(u, c, silent=True), pattern="^back_to_main$")
            ],
            
            allow_reentry=True
        )
        
        # Drug management handler
        drug_handler = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex('^اضافه کردن دارو$'), add_drug_item),
                InlineQueryHandler(handle_inline_query),
                ChosenInlineResultHandler(handle_chosen_inline_result),
                MessageHandler(filters.Regex('^لیست داروهای من$'), list_my_drugs),
                CallbackQueryHandler(edit_drugs, pattern="^edit_drugs$"),
                CallbackQueryHandler(edit_drug_item, pattern="^edit_drug_"),
                CallbackQueryHandler(handle_drug_edit_action, pattern="^(edit_date|edit_quantity|delete_drug)$"),
                CallbackQueryHandler(handle_drug_deletion, pattern="^(confirm_delete|cancel_delete)$"),
                CallbackQueryHandler(search_drug_for_adding, pattern="^back_to_search$"),
                CallbackQueryHandler(select_drug_for_adding, pattern="^select_drug_|back_to_drug_selection$")
            ],
            states={
                States.SEARCH_DRUG_FOR_ADDING: [
                    InlineQueryHandler(handle_inline_query),
                    CallbackQueryHandler(handle_add_drug_callback, pattern="^add_drug_"),
                    ChosenInlineResultHandler(handle_chosen_inline_result),
                    CallbackQueryHandler(add_drug_item, pattern="^back$"),
                    MessageHandler(filters.Regex('^(جستجوی دارو|لیست داروهای من|ثبت نیاز جدید|لیست نیازهای من|ساخت کد پرسنل|تنظیم شاخه‌های دارویی)$'), 
                     handle_state_change)
                ],
                States.ADD_DRUG_DATE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, add_drug_date),
                    CallbackQueryHandler(search_drug_for_adding, pattern="^back_to_search$"),
                    MessageHandler(filters.Regex('^(جستجوی دارو|لیست داروهای من|ثبت نیاز جدید|لیست نیازهای من|ساخت کد پرسنل|تنظیم شاخه‌های دارویی)$'), 
                     handle_state_change)
                ],
                States.ADD_DRUG_QUANTITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_drug_item),
                    CallbackQueryHandler(handle_back, pattern="^back$"),
                    MessageHandler(filters.Regex('^(جستجوی دارو|لیست داروهای من|ثبت نیاز جدید|لیست نیازهای من|ساخت کد پرسنل|تنظیم شاخه‌های دارویی)$'), 
                     handle_state_change)
                ],
                States.EDIT_DRUG: [
    # مدیریت دکمه‌های بازگشت
                    MessageHandler(filters.Regex(r'^(🔙 بازگشت|🔙 بازگشت به لیست داروها|🔙 بازگشت به منوی اصلی)$'), 
                      handle_back_from_edit_drug),
    
    # مدیریت دکمه‌های عملیاتی ویرایش
                    MessageHandler(filters.Regex(r'^(✏️ ویرایش تاریخ|✏️ ویرایش تعداد|🗑️ حذف دارو)$'), 
                       handle_drug_edit_action_from_keyboard),
    
    # مدیریت تأیید حذف
                    MessageHandler(filters.Regex(r'^(✅ بله، حذف شود|❌ خیر، انصراف)$'), 
                     handle_drug_deletion_confirmation),
    
    # مدیریت انتخاب دارو از لیست (دکمه‌های ✏️ نام دارو)
                    MessageHandler(filters.Regex(r'^(✏️ .+)$'), handle_select_drug_for_edit),
    
    # ذخیره ویرایش تاریخ و تعداد
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_drug_edit),
    
    # تغییر state به منوهای دیگر
                    MessageHandler(filters.Regex(r'^(اضافه کردن دارو|جستجوی دارو|لیست داروهای من|ثبت نیاز جدید|لیست نیازهای من|ساخت کد پرسنل|تنظیم شاخه‌های دارویی)$'), 
                      handle_state_change)

                ]
            },
            fallbacks=[
                CommandHandler('cancel', lambda u, c: clear_conversation_state(u, c, silent=True)),
                MessageHandler(filters.Regex(r'^(جستجوی دارو|لیست داروهای من|ثبت نیاز جدید|لیست نیازهای من|ساخت کد پرسنل|تنظیم شاخه‌های دارویی)$'), 
                     handle_state_change),
                CallbackQueryHandler(lambda u, c: clear_conversation_state(u, c, silent=True), pattern="^back_to_main$")
            ],
            allow_reentry=True,
            per_chat=False,
            per_user=True
        )
        
        # Needs management handler
        needs_handler = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex('^ثبت نیاز جدید$'), add_need),
                MessageHandler(filters.Regex('^لیست نیازهای من$'), list_my_needs),
                MessageHandler(filters.Regex('^✏️ ویرایش نیازها$'), handle_edit_needs_button),
          #      CallbackQueryHandler(edit_needs, pattern="^edit_needs$"),
          #      CallbackQueryHandler(edit_need_item, pattern="^edit_need_"),
            #    CallbackQueryHandler(handle_need_edit_action, pattern="^(edit_need_name|edit_need_desc|edit_need_quantity|delete_need)$"),
             #   CallbackQueryHandler(handle_need_deletion, pattern="^(confirm_need_delete|cancel_need_delete)$"),
                CallbackQueryHandler(handle_need_drug_selection, pattern="^need_drug_") 
            ],
            states={
                States.SEARCH_DRUG_FOR_NEED: [
                    InlineQueryHandler(handle_inline_query),
                    CallbackQueryHandler(handle_need_drug_callback, pattern="^need_drug_"),
                    ChosenInlineResultHandler(handle_chosen_inline_result),
                    CallbackQueryHandler(add_need, pattern="^back$")
                    
    
                    
                ],
                States.ADD_NEED_QUANTITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, add_need_quantity),
                    CallbackQueryHandler(handle_back, pattern="^back$"),
                    CallbackQueryHandler(clear_conversation_state, pattern="^back_to_main$")
            
                ],
                States.EDIT_NEED: [
                    MessageHandler(filters.Regex(r'^(🔙 بازگشت|🔙 بازگشت به لیست نیازها|🔙 بازگشت به منوی اصلی)$'), 
                                handle_back_from_edit_need),
    
    # سپس: دکمه‌های عملیاتی
                    MessageHandler(filters.Regex(r'^(✏️ ویرایش تعداد|🗑️ حذف نیاز)$'), 
                                handle_need_edit_action_from_keyboard),
                    MessageHandler(filters.Regex(r'^(✅ بله، حذف شود|❌ خیر، انصراف)$'), 
                                handle_need_deletion_confirmation),
    
    # سپس: انتخاب نیاز از لیست
                    MessageHandler(filters.Regex(r'^(✏️ .+)$'), handle_select_need_for_edit),
    
    # 🔥 سپس: ذخیره ویرایش (فقط برای تعداد) - این باید آخر باشد
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_need_edit),
                    #CallbackQueryHandler(edit_needs, pattern="^back_to_needs_list$"),
                   # CallbackQueryHandler(edit_need_item, pattern="^edit_need_"),
                  #  CallbackQueryHandler(handle_need_edit_action, pattern="^(edit_need_name|edit_need_desc|edit_need_quantity|delete_need)$"),
                  #  CallbackQueryHandler(handle_need_deletion, pattern="^(confirm_need_delete|cancel_need_delete)$")

                ]
            },
            fallbacks=[
                CommandHandler('cancel', lambda u, c: clear_conversation_state(u, c, silent=True)),
                MessageHandler(filters.Regex(r'^(جستجوی دارو|لیست داروهای من|ثبت نیاز جدید|لیست نیازهای من|ساخت کد پرسنل|تنظیم شاخه‌های دارویی)$'), 
                     handle_state_change),
                CallbackQueryHandler(lambda u, c: clear_conversation_state(u, c, silent=True), pattern="^back_to_main$")
            ],      
            allow_reentry=True,
            per_chat=False,
            per_user=True
        )
        
        # Search and trade handler
        trade_handler = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex(r'^جستجوی دارو$'), search_drug),
                MessageHandler(filters.Regex('^اضافه کردن دارو$'), add_drug_item),
                MessageHandler(filters.Regex('^لیست داروهای من$'), list_my_drugs),
                CallbackQueryHandler(handle_match_notification, pattern=r'^view_match_'),
                CallbackQueryHandler(edit_drugs, pattern="^edit_drugs$"),
                CallbackQueryHandler(search_drug_for_adding, pattern="^back_to_search$"),
                CallbackQueryHandler(select_drug_for_adding, pattern="^select_drug_|back_to_drug_selection$")
            ],
            states={
                States.SEARCH_DRUG: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search),
                    MessageHandler(
                    filters.Regex(r'^(اضافه کردن دارو|لیست داروهای من|ثبت نیاز جدید|لیست نیازهای من|ساخت کد پرسنل|تنظیم شاخه‌های دارویی)$'), 
                    handle_state_change)
                ],
                States.SELECT_PHARMACY: [
                    CallbackQueryHandler(select_pharmacy, pattern=r'^pharmacy_\d+$'),
                    CallbackQueryHandler(handle_back, pattern=r'^back$')
                ],
                States.SELECT_DRUGS: [
                    MessageHandler(
                        filters.Regex(
                            r'^(📌 \d+ - .+|💊 \d+ - .+|📌 صفحه قبل|📌 صفحه بعد|💊 صفحه قبل|💊 صفحه بعد|📌 داروهای داروخانه هدف|💊 داروهای شما|✅ اتمام انتخاب|🔙 بازگشت به داروخانه‌ها)$'
                        ),
                        handle_drug_selection_from_keyboard
                    ),
                    MessageHandler(filters.Regex(r'^🔙 بازگشت به داروخانه‌ها$'), handle_back_button),
                    MessageHandler(filters.Regex(r'^✅ اتمام انتخاب$'), handle_finish_selection),
                    CallbackQueryHandler(show_two_column_selection, pattern=r'^edit_selection$'),
                    CallbackQueryHandler(show_two_column_selection, pattern=r'^add_more$'),
                    CallbackQueryHandler(handle_back_to_pharmacies, pattern=r'^back_to_pharmacies$')
                ],
                States.SELECT_QUANTITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, enter_quantity),
                    CallbackQueryHandler(show_two_column_selection, pattern=r'^back_to_selection$')
                ],
                States.COMPENSATION_SELECTION: [
                    CallbackQueryHandler(show_two_column_selection, pattern=r'^add_more$'),
                    CallbackQueryHandler(handle_compensation_selection, pattern=r'^compensate$'),
                    CallbackQueryHandler(handle_compensation_selection, pattern=r'^comp_\d+$'),
                    CallbackQueryHandler(confirm_totals, pattern=r'^comp_finish$')
                ],
                States.COMPENSATION_QUANTITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_compensation_quantity),
                    CallbackQueryHandler(show_two_column_selection, pattern=r'^back_to_compensation$')
                ],
                States.CONFIRM_OFFER: [
                    CallbackQueryHandler(confirm_offer, pattern=r'^confirm_offer$'),
                    CallbackQueryHandler(send_offer, pattern=r'^send_offer$'),
                    CallbackQueryHandler(show_two_column_selection, pattern=r'^edit_selection$'),
                    CallbackQueryHandler(show_two_column_selection, pattern=r'^add_more$'),
                    CallbackQueryHandler(handle_back_to_pharmacies, pattern=r'^back_to_selection$')
                ],
                States.CONFIRM_TOTALS: [
                    CallbackQueryHandler(show_two_column_selection, pattern=r'^edit_selection$'),
                    CallbackQueryHandler(confirm_totals, pattern=r'^back_to_totals$'),
                    CallbackQueryHandler(send_offer, pattern=r'^send_offer$')
                ]
            },
            fallbacks=[
                CommandHandler('cancel', lambda u, c: clear_conversation_state(u, c, silent=True)),
                MessageHandler(filters.Regex(r'^(جستجوی دارو|لیست داروهای من|ثبت نیاز جدید|لیست نیازهای من|ساخت کد پرسنل|تنظیم شاخه‌های دارویی)$'), 
                     handle_state_change),
                CallbackQueryHandler(lambda u, c: clear_conversation_state(u, c, silent=True), pattern="^back_to_main$")
            ],
            allow_reentry=True,
            per_chat=False,
            per_user=True
        )
        
        # Medical categories handler
        categories_handler = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex('^تنظیم شاخه‌های دارویی$'), setup_medical_categories),
                CallbackQueryHandler(toggle_category, pattern="^togglecat_"),
                CallbackQueryHandler(save_categories, pattern="^save_categories$")
            ],
            states={
                States.SETUP_CATEGORIES: [
                    CallbackQueryHandler(toggle_category, pattern="^togglecat_"),
                    CallbackQueryHandler(save_categories, pattern="^save_categories$")
                ]
            },
            fallbacks=[
                CommandHandler('cancel', lambda u, c: clear_conversation_state(u, c, silent=True)),
                MessageHandler(filters.Regex(r'^(جستجوی دارو|لیست داروهای من|ثبت نیاز جدید|لیست نیازهای من|ساخت کد پرسنل|تنظیم شاخه‌های دارویی)$'), 
                     handle_state_change),
                CallbackQueryHandler(lambda u, c: clear_conversation_state(u, c, silent=True), pattern="^back_to_main$")
            ],
            allow_reentry=True
        )
        
        # Admin commands handler
        admin_handler = ConversationHandler(
            entry_points=[
                CommandHandler('upload_excel', upload_excel_start),
                CommandHandler('verify', verify_pharmacy)
            ],
            states={
                States.ADMIN_UPLOAD_EXCEL: [
                    MessageHandler(filters.Document.ALL | (filters.TEXT & filters.Entity("url")), handle_excel_upload)
                ]
            },
            # در همه ConversationHandlerها:
            fallbacks=[
                CommandHandler('cancel', lambda u, c: clear_conversation_state(u, c, silent=True)),
                MessageHandler(filters.Regex(r'^(جستجوی دارو|لیست داروهای من|ثبت نیاز جدید|لیست نیازهای من|ساخت کد پرسنل|تنظیم شاخه‌های دارویی)$'), 
                     handle_state_change),
                CallbackQueryHandler(lambda u, c: clear_conversation_state(u, c, silent=True), pattern="^back_to_main$")
            ],
            allow_reentry=True
        )
        
        # Add handlers
        application.add_handler(CommandHandler('start', start))
        application.add_handler(admin_verify_handler)
        application.add_handler(registration_handler)
        application.add_handler(simple_verify_handler)
        application.add_handler(personnel_handler)
        application.add_handler(drug_handler)
        application.add_handler(needs_handler)
        application.add_handler(trade_handler)
        # In your main application setup
        
        application.add_handler(categories_handler)
        application.add_handler(admin_handler)
        application.add_handler(InlineQueryHandler(handle_inline_query))
        application.add_handler(ChosenInlineResultHandler(handle_chosen_inline_result))
        application.add_handler(MessageHandler(filters.Regex('^ساخت کد پرسنل$'), generate_personnel_code))
        application.add_handler(CallbackQueryHandler(approve_user, pattern="^approve_user_"))
        application.add_handler(CallbackQueryHandler(reject_user, pattern="^reject_user_"))
        
        application.add_handler(CallbackQueryHandler(approve_user_callback, pattern="^approve_"))
        application.add_handler(CallbackQueryHandler(approve_user_callback, pattern="^reject_"))
        application.add_handler(CallbackQueryHandler(approve_user, pattern="^approve_user_"))
        application.add_handler(CallbackQueryHandler(reject_user, pattern="^reject_user_"))
        application.add_handler(CallbackQueryHandler(confirm_offer, pattern="^confirm_offer$"))
        application.add_handler(CallbackQueryHandler(submit_offer, pattern="^submit_offer$"))
        application.add_handler(CallbackQueryHandler(handle_back_to_pharmacies, pattern="^back_to_pharmacies$"))
        
        application.add_handler(MessageHandler(filters.Regex('^منوی اصلی$'), main_menu_access))
        application.add_handler(MessageHandler(filters.Regex('^منوی اصلی$'), clear_conversation_state))
        application.add_handler(MessageHandler(filters.Regex('^🔙 بازگشت به منوی اصلی$'), clear_conversation_state))
        application.add_handler(CommandHandler('menu', clear_conversation_state))
        application.add_handler(CommandHandler('cancel', clear_conversation_state))
        application.add_handler(MessageHandler(filters.Regex('^🔙 بازگشت به منوی اصلی$'), handle_state_change))
        application.add_handler(CommandHandler('cancel', handle_state_change))
        application.add_handler(MessageHandler(
        filters.Regex(r'^(اضافه کردن دارو|جستجوی دارو|لیست داروهای من|ثبت نیاز جدید|لیست نیازهای من|ساخت کد پرسنل|تنظیم شاخه‌های دارویی)$'),
        handle_state_change  # تابعی که state رو پاک میکنه و عملیات رو شروع میکنه
        ))
        application.add_handler(CallbackQueryHandler(handle_need_drug_callback, pattern="^need_drug_"))
        # در بخش اضافه کردن هندلرها:
        application.add_handler(MessageHandler(filters.Regex('^🔙 بازگشت به منوی اصلی$'), clear_conversation_state))
        application.add_handler(CallbackQueryHandler(handle_add_drug_callback, pattern="^add_drug_"))
        # Add ban user command
        # Add ban user command - فقط برای messageها
        application.add_handler(CommandHandler('ban_user', ban_user, filters=filters.ChatType.PRIVATE))
        # Add restart handler for banned users
        
        application.add_handler(CallbackQueryHandler(handle_restart_after_ban, pattern="^restart_after_ban$"))

        # Add error handler
        application.add_error_handler(error_handler)
        
        # Start the Bot
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.critical(f"Fatal error in main: {e}")
        raise

if __name__ == '__main__':
    main()
