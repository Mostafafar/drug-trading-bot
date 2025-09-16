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
    VERIFICATION_CODE = auto()
    REGISTER_ADDRESS = auto()
    ADMIN_VERIFICATION = auto()
    SIMPLE_VERIFICATION = auto()
    SEARCH_DRUG = auto()
    SELECT_PHARMACY = auto()
    SELECT_DRUGS = auto()
    SELECT_QUANTITY = auto()
    CONFIRM_OFFER = auto()
    ADD_NEED_NAME = auto()
    ADD_NEED_DESC = auto()
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
    SEARCH_DRUG_FOR_NEED = auto()  # اضافه کردن این خط

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
        with conn.cursor() as cursor:
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
            )''')
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS personnel_codes (
                code TEXT PRIMARY KEY,
                creator_id BIGINT REFERENCES pharmacies(user_id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )''')
            cursor.execute("SELECT to_regclass('users')")
            users_table = cursor.fetchone()[0]
            logger.info(f"Users table exists: {users_table}")
            if not users_table:
                raise Exception("Users table creation failed")
            
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
            )''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS drug_items (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(id),
                name TEXT,
                price TEXT,
                date TEXT,
                quantity INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS medical_categories (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE
            )''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_categories (
                user_id BIGINT REFERENCES users(id),
                category_id INTEGER REFERENCES medical_categories(id),
                PRIMARY KEY (user_id, category_id)
            )''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS offers (
                id SERIAL PRIMARY KEY,
                pharmacy_id BIGINT REFERENCES pharmacies(user_id),
                buyer_id BIGINT REFERENCES users(id),
                status TEXT DEFAULT 'pending',
                total_price NUMERIC,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS offer_items (
                id SERIAL PRIMARY KEY,
                offer_id INTEGER REFERENCES offers(id),
                drug_name TEXT,
                price TEXT,
                quantity INTEGER,
                item_type TEXT DEFAULT 'drug'
            )''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS compensation_items (
                id SERIAL PRIMARY KEY,
                offer_id INTEGER REFERENCES offers(id),
                drug_id INTEGER REFERENCES drug_items(id),
                quantity INTEGER
            )''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_needs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(id),
                name TEXT,
                description TEXT,
                quantity INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS match_notifications (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(id),
                drug_id INTEGER REFERENCES drug_items(id),
                need_id INTEGER REFERENCES user_needs(id),
                similarity_score REAL,
                notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_settings (
                id SERIAL PRIMARY KEY,
                excel_url TEXT,
                last_updated TIMESTAMP
            )''')
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
            )''')

            cursor.execute('''
            CREATE TABLE IF NOT EXISTS exchange_items (
               id SERIAL PRIMARY KEY,
               exchange_id INTEGER REFERENCES exchanges(id),
               drug_id INTEGER REFERENCES drug_items(id),
               drug_name TEXT,
               price TEXT,
               quantity INTEGER,
               from_pharmacy BOOLEAN
            )''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS simple_codes (
                code TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_by BIGINT[] DEFAULT array[]::BIGINT[],
                max_uses INTEGER DEFAULT 5
            )''')
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            
            default_categories = ['اعصاب', 'قلب', 'ارتوپد', 'زنان', 'گوارش', 'پوست', 'اطفال']
            for category in default_categories:
                cursor.execute('''
                INSERT INTO medical_categories (name)
                VALUES (%s)
                ON CONFLICT (name) DO NOTHING
                ''', (category,))
            
            cursor.execute('''
            INSERT INTO users (id, is_admin, is_verified)
            VALUES (%s, TRUE, TRUE)
            ON CONFLICT (id) DO UPDATE SET is_admin = TRUE
            ''', (ADMIN_CHAT_ID,))
            
            conn.commit()
    except psycopg2.Error as e:
        logger.error(f"Database initialization error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
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
    """Clear the conversation state without showing cancellation message"""
    try:
        # حفظ pharmacy_id و pharmacy_name قبل از پاک کردن
        pharmacy_id = context.user_data.get('selected_pharmacy_id')
        pharmacy_name = context.user_data.get('selected_pharmacy_name')
        
        # پاک کردن تمام stateهای مربوط به عملیات مختلف
        keys_to_remove = [
            # داروها
            'selected_drug', 'expiry_date', 'drug_quantity', 'editing_drug', 
            'edit_field', 'matched_drugs', 'current_selection',
            
            # نیازها
            'need_name', 'need_desc', 'editing_need',
            
            # جستجو و مبادله
            'offer_items', 'comp_items', 'current_list', 
            'page_target', 'page_mine', 'match_drug', 'match_need',
            'current_comp_drug', 'target_drugs', 'my_drugs',
            
            # سایر
            'pharmacy_name', 'founder_name', 'national_card',
            'license', 'medical_card', 'phone', 'address',
            'verification_code'
        ]
        
        for key in keys_to_remove:
            if key in context.user_data:
                del context.user_data[key]
        
        # بازگرداندن pharmacy_id و pharmacy_name اگر وجود داشتند
        if pharmacy_id is not None:
            context.user_data['selected_pharmacy_id'] = pharmacy_id
        if pharmacy_name is not None:
            context.user_data['selected_pharmacy_name'] = pharmacy_name
        
        if silent:
            return ConversationHandler.END
            
        # فقط اگر silent نباشد پیام نشان دهد
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['لیست داروهای من', 'ثبت نیاز جدید'],
            ['لیست نیازهای من', 'ساخت کد پرسنل'],
            ['تنظیم شاخه‌های دارویی']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        if update.callback_query:
            await update.callback_query.answer()
            try:
                await update.callback_query.edit_message_text(
                    text="به منوی اصلی بازگشتید:",
                    reply_markup=reply_markup
                )
            except:
                await context.bot.send_message(
                    chat_id=update.callback_query.message.chat_id,
                    text="به منوی اصلی بازگشتید:",
                    reply_markup=reply_markup
                )
        elif update.message:
            await update.message.reply_text(
                text="به منوی اصلی بازگشتید:",
                reply_markup=reply_markup
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="به منوی اصلی بازگشتید:",
                reply_markup=reply_markup
            )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in clear_conversation_state: {e}")
        return ConversationHandler.END
# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler with both registration options and verification check"""
    try:
        await ensure_user(update, context)
        
        # Check verification status
        is_verified = False
        is_pharmacy_admin = False
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                SELECT u.is_verified, u.is_pharmacy_admin
                FROM users u
                WHERE u.id = %s
                ''', (update.effective_user.id,))
                result = cursor.fetchone()
                if result:
                    is_verified, is_pharmacy_admin = result
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
        
        # Different menu for pharmacy admin vs regular users
        if is_pharmacy_admin:
            keyboard = [
                ['اضافه کردن دارو', 'جستجوی دارو'],
                ['لیست داروهای من', 'ثبت نیاز جدید'],
                ['لیست نیازهای من', 'ساخت کد پرسنل'],
                ['تنظیم شاخه‌های دارویی']
            ]
            welcome_msg = "به پنل مدیریت داروخانه خوش آمدید."
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
    # بقیه کد...
    
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

        # Handle different callback patterns
        if query.data.startswith("approve_user_"):
            return await approve_user(update, context)
        elif query.data.startswith("reject_user_"):
            return await reject_user(update, context)
        if query.data.startswith("add_drug_"):
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
            phone_number = update.message.text
        
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
                
                # ارسال پیام به کاربر
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="✅ حساب شما توسط ادمین تایید شد!\n\n"
                             "شما اکنون می‌توانید از تمام امکانات مدیریت داروخانه استفاده کنید."
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
    """Get national card photo in registration process"""
    try:
        founder_name = update.message.text
        context.user_data['founder_name'] = founder_name
        
        await update.message.reply_text(
            "لطفا تصویر کارت ملی را ارسال کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.REGISTER_NATIONAL_CARD
    except Exception as e:
        logger.error(f"Error in register_national_card: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def register_license(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get license photo in registration process"""
    try:
        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
        elif update.message.document:
            photo_file = await update.message.document.get_file()
        else:
            await update.message.reply_text("لطفا یک تصویر ارسال کنید.")
            return States.REGISTER_NATIONAL_CARD
        
        file_path = await download_file(photo_file, "national_card", update.effective_user.id)
        context.user_data['national_card'] = file_path
        
        await update.message.reply_text(
            "لطفا تصویر پروانه داروخانه را ارسال کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.REGISTER_LICENSE
    except Exception as e:
        logger.error(f"Error in register_license: {e}")
        await update.message.reply_text("خطایی در دریافت تصویر رخ داد. لطفا دوباره تلاش کنید.")
        return States.REGISTER_NATIONAL_CARD

async def register_medical_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get medical card photo in registration process"""
    try:
        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
        elif update.message.document:
            photo_file = await update.message.document.get_file()
        else:
            await update.message.reply_text("لطفا یک تصویر ارسال کنید.")
            return States.REGISTER_LICENSE
        
        file_path = await download_file(photo_file, "license", update.effective_user.id)
        context.user_data['license'] = file_path
        
        await update.message.reply_text(
            "لطفا تصویر کارت نظام پزشکی را ارسال کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.REGISTER_MEDICAL_CARD
    except Exception as e:
        logger.error(f"Error in register_medical_card: {e}")
        await update.message.reply_text("خطایی در دریافت تصویر رخ داد. لطفا دوباره تلاش کنید.")
        return States.REGISTER_LICENSE

async def register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get phone number in registration process"""
    try:
        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
        elif update.message.document:
            photo_file = await update.message.document.get_file()
        else:
            await update.message.reply_text("لطفا یک تصویر ارسال کنید.")
            return States.REGISTER_MEDICAL_CARD
        
        file_path = await download_file(photo_file, "medical_card", update.effective_user.id)
        context.user_data['medical_card'] = file_path
        
        keyboard = [[KeyboardButton("اشتراک گذاری شماره تلفن", request_contact=True)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            "لطفا شماره تلفن خود را با استفاده از دکمه زیر ارسال کنید:",
            reply_markup=reply_markup
        )
        return States.REGISTER_PHONE
    except Exception as e:
        logger.error(f"Error in register_phone: {e}")
        await update.message.reply_text("خطایی در دریافت تصویر رخ داد. لطفا دوباره تلاش کنید.")
        return States.REGISTER_MEDICAL_CARD

async def register_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get address in registration process"""
    try:
        if update.message.contact:
            phone = update.message.contact.phone_number
        else:
            phone = update.message.text
        
        context.user_data['phone'] = phone
        
        await update.message.reply_text(
            "لطفا آدرس داروخانه را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.REGISTER_ADDRESS
    except Exception as e:
        logger.error(f"Error in register_address: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def verify_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify registration code"""
    try:
        address = update.message.text
        context.user_data['address'] = address
        
        verification_code = str(random.randint(1000, 9999))
        context.user_data['verification_code'] = verification_code
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Save user with verification code
                cursor.execute('''
                INSERT INTO users (id, first_name, last_name, username, phone, verification_code, verification_method)
                VALUES (%s, %s, %s, %s, %s, %s, 'full_registration')
                ON CONFLICT (id) DO UPDATE SET
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    username = EXCLUDED.username,
                    phone = EXCLUDED.phone,
                    verification_code = EXCLUDED.verification_code,
                    verification_method = 'full_registration'
                ''', (
                    update.effective_user.id,
                    update.effective_user.first_name,
                    update.effective_user.last_name,
                    update.effective_user.username,
                    context.user_data.get('phone'),
                    verification_code
                ))
                
                conn.commit()
        except Exception as e:
            logger.error(f"Error saving user: {e}")
            await update.message.reply_text("خطا در ثبت اطلاعات. لطفا دوباره تلاش کنید.")
            return ConversationHandler.END
        finally:
            if conn:
                conn.close()
        
        await update.message.reply_text(
            f"کد تایید شما: {verification_code}\n\n"
            "لطفا این کد را برای تکمیل ثبت نام وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.VERIFICATION_CODE
    except Exception as e:
        logger.error(f"Error in verify_code: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def complete_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Complete registration by verifying code"""
    try:
        user_code = update.message.text.strip()
        stored_code = context.user_data.get('verification_code')
        
        if user_code == stored_code:
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor() as cursor:
                    # Save pharmacy information
                    cursor.execute('''
                    INSERT INTO pharmacies (
                        user_id, name, founder_name, national_card_image,
                        license_image, medical_card_image, phone, address,
                        verified
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        update.effective_user.id,
                        context.user_data.get('pharmacy_name'),
                        context.user_data.get('founder_name'),
                        context.user_data.get('national_card'),
                        context.user_data.get('license'),
                        context.user_data.get('medical_card'),
                        context.user_data.get('phone'),
                        context.user_data.get('address'),
                        False
                    ))
                    
                    # Mark user as verified
                    cursor.execute('''
                    UPDATE users 
                    SET is_verified = TRUE 
                    WHERE id = %s
                    ''', (update.effective_user.id,))
                    
                    conn.commit()
                    
                    await update.message.reply_text(
                        "✅ ثبت نام شما با موفقیت انجام شد!\n\n"
                        "اطلاعات شما برای تایید نهایی به ادمین ارسال شد. پس از تایید می‌توانید از تمام امکانات ربات استفاده کنید."
                    )
                    
                    # Notify admin
                    try:
                        await context.bot.send_message(
                            chat_id=ADMIN_CHAT_ID,
                            text=f"📌 درخواست ثبت نام جدید:\n\n"
                                 f"داروخانه: {context.user_data.get('pharmacy_name')}\n"
                                 f"مدیر: {context.user_data.get('founder_name')}\n"
                                 f"تلفن: {context.user_data.get('phone')}\n"
                                 f"آدرس: {context.user_data.get('address')}\n\n"
                                 f"برای تایید از دستور /verify_{update.effective_user.id} استفاده کنید."
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify admin: {e}")
                    
            except Exception as e:
                logger.error(f"Error completing registration: {e}")
                await update.message.reply_text("خطا در تکمیل ثبت نام. لطفا دوباره تلاش کنید.")
            finally:
                if conn:
                    conn.close()
            
            return ConversationHandler.END
        else:
            await update.message.reply_text("کد تایید نامعتبر است. لطفا دوباره تلاش کنید.")
            return States.VERIFICATION_CODE
    except Exception as e:
        logger.error(f"Error in complete_registration: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

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
    """Handle need drug selection from inline query result"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data.startswith("need_drug_"):
            idx = int(query.data.split("_")[2])
            if 0 <= idx < len(drug_list):
                selected_drug = drug_list[idx]
                context.user_data['need_drug'] = {
                    'name': selected_drug[0],
                    'price': selected_drug[1]
                }
                
                await query.edit_message_text(
                    f"✅ داروی مورد نیاز انتخاب شد: {selected_drug[0]}\n💰 قیمت مرجع: {selected_drug[1]}\n\n"
                    "📝 لطفا توضیحاتی درباره این نیاز وارد کنید (اختیاری):",
                    reply_markup=None
                )
                return States.ADD_NEED_DESC
                
    except Exception as e:
        logger.error(f"Error handling need drug callback: {e}")
        await query.edit_message_text("خطا در انتخاب دارو. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def add_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start process to add a drug item with inline query"""
    await clear_conversation_state(update, context, silent=True)
    try:
        await ensure_user(update, context)
        
        # ایجاد دکمه برای جستجوی اینلاین برای اضافه کردن دارو
        keyboard = [
            [InlineKeyboardButton(
                "🔍 جستجوی دارو برای اضافه کردن", 
                switch_inline_query_current_chat="add "
            )],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
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
    
    # تشخیص نوع جستجو (اضافه کردن دارو یا نیاز)
    search_type = "add"
    if query.startswith("need "):
        search_type = "need"
        query = query[5:].strip()  # حذف "need " از ابتدای کوئری
    elif query.startswith("add "):
        query = query[4:].strip()  # حذف "add " از ابتدای کوئری
    
    if not query:
        # اگر کوئری خالی است، همه داروها را نشان بده
        query = ""
    
    results = []
    for idx, (name, price) in enumerate(drug_list):
        if query.lower() in name.lower():
            # جدا کردن نام و توضیحات
            title_part = name.split()[0] if name.split() else name
            desc_part = ' '.join(name.split()[1:]) if len(name.split()) > 1 else name
            
            if search_type == "add":
                # فقط گزینه اضافه کردن دارو
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
            else:
                # فقط گزینه ثبت نیاز
                results.append(
                    InlineQueryResultArticle(
                        id=f"need_{idx}",
                        title=f"📝 {title_part}",
                        description=f"{desc_part} - قیمت: {price}",
                        input_message_content=InputTextMessageContent(
                            f"💊 {name}\n💰 قیمت: {price}"
                        ),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                "📝 ثبت به عنوان نیاز",
                                callback_data=f"need_drug_{idx}"
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
            
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ دارو انتخاب شده: {drug_name}\n💰 قیمت: {drug_price}\n\n📅 لطفا تاریخ انقضا را وارد کنید (مثال: 2026/01/23):"
            )
            
        elif result_id.startswith('need_'):
            # پردازش برای ثبت نیاز
            idx = int(result_id.split('_')[1])
            drug_name, drug_price = drug_list[idx]
            
            context.user_data['need_drug'] = {
                'name': drug_name.strip(),
                'price': drug_price.strip()
            }
            
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ داروی مورد نیاز انتخاب شد: {drug_name}\n💰 قیمت مرجع: {drug_price}\n\n📝 لطفا توضیحاتی درباره این نیاز وارد کنید (اختیاری):"
            )
            
    except Exception as e:
        logger.error(f"Error in handle_chosen_inline_result: {e}")
        await context.bot.send_message(
            chat_id=update.chosen_inline_result.from_user.id,
            text="خطایی در انتخاب دارو رخ داد. لطفا دوباره تلاش کنید."
            )
async def search_drug_for_adding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع جستجو با اینلاین کوئری"""
    await clear_conversation_state(update, context, silent=True)
    keyboard = [
        [InlineKeyboardButton("🔍 جستجوی دارو", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
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



# ... (بقیه importها و کدهای قبلی بدون تغییر)

async def add_drug_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message and update.message.text:
            expiry_date = update.message.text.strip()
            logger.info(f"User {update.effective_user.id} entered expiry date: {expiry_date}")
            
            # Validate date format (simple validation)
            if not re.match(r'^\d{4}/\d{2}/\d{2}$', expiry_date):
                await update.message.reply_text("فرمت تاریخ نامعتبر است. لطفا تاریخ را به فرمت 2026/01/23 وارد کنید:")
                return States.ADD_DRUG_DATE
            
            context.user_data['expiry_date'] = expiry_date
            logger.info(f"Stored expiry_date: {expiry_date} for user {update.effective_user.id}")
            
            await update.message.reply_text("📦 لطفا تعداد موجودی را وارد کنید:")
            return States.ADD_DRUG_QUANTITY
            
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
    try:
        # Get all required data from context
        selected_drug = context.user_data.get('selected_drug', {})
        expiry_date = context.user_data.get('expiry_date')
        quantity = update.message.text.strip()

        # Validate all required fields
        if not selected_drug or not expiry_date:
            await update.message.reply_text(
                "اطلاعات دارو ناقص است. لطفا دوباره از ابتدا شروع کنید:\n"
                "1. روی دکمه 'اضافه کردن دارو' کلیک کنید\n"
                "2. دارو را از لیست انتخاب کنید\n"
                "3. تاریخ انقضا و تعداد را وارد کنید"
            )
            return ConversationHandler.END

        # Validate quantity
        try:
            quantity = int(quantity)
            if quantity <= 0:
                await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید:")
                return States.ADD_DRUG_QUANTITY
        except ValueError:
            await update.message.reply_text("لطفا یک عدد صحیح وارد کنید:")
            return States.ADD_DRUG_QUANTITY

        # Save to database
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
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
                conn.commit()
                
                await update.message.reply_text(
                    f"✅ دارو با موفقیت ثبت شد:\n"
                    f"💊 نام: {selected_drug['name']}\n"
                    f"💰 قیمت: {selected_drug['price']}\n"
                    f"📅 تاریخ انقضا: {expiry_date}\n"
                    f"📦 تعداد: {quantity}"
                )
                
                # Clear context
                context.user_data.pop('selected_drug', None)
                context.user_data.pop('expiry_date', None)
                
                return await start(update, context)  # Return to main menu
                
        except Exception as e:
            logger.error(f"Error saving drug item for user {update.effective_user.id}: {e}")
            if conn:
                conn.rollback()
            await update.message.reply_text("خطا در ثبت دارو. لطفا دوباره تلاش کنید.")
            return ConversationHandler.END
        finally:
            if conn:
                conn.close()
                
    except Exception as e:
        logger.error(f"Error in save_drug_item for user {update.effective_user.id}: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
async def list_my_drugs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست داروهای کاربر بدون پیام لغو"""
    try:
        # پاک کردن stateهای قبلی (بی صدا)
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
                    for drug in drugs:
                        drug_name = drug['name']
                        if len(drug_name) > 50:
                            drug_name = drug_name[:47] + "..."
                        
                        message += (
                            f"• {drug_name}\n"
                            f"  قیمت: {drug['price']}\n"
                            f"  تاریخ انقضا: {drug['date']}\n"
                            f"  موجودی: {drug['quantity']}\n\n"
                        )
                    
                    keyboard = [
                        [InlineKeyboardButton("✏️ ویرایش داروها", callback_data="edit_drugs")],
                        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_main")]
                    ]
                    
                    await update.message.reply_text(
                        message,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    return States.EDIT_DRUG
                else:
                    await update.message.reply_text(
                        "شما هنوز هیچ دارویی اضافه نکرده‌اید."
                    )
                    
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
    """Start drug editing process"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()

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
                
                if not drugs:
                    await query.edit_message_text("هیچ دارویی برای ویرایش وجود ندارد.")
                    return ConversationHandler.END
                
                # در تابع edit_drugs:
                keyboard = []
                for drug in drugs:
                    display_text = f"{format_button_text(drug['name'])}\nموجودی: {drug['quantity']}"
                    keyboard.append([InlineKeyboardButton(
                        display_text,
                        callback_data=f"edit_drug_{drug['id']}"
                    )])
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back")])
                await query.edit_message_text(
                    "لطفا دارویی که می‌خواهید ویرایش کنید را انتخاب کنید:",
                    reply_markup=InlineKeyboardMarkup(keyboard))
                return States.EDIT_DRUG
                
        except Exception as e:
            logger.error(f"Error in edit_drugs: {e}")
            await query.edit_message_text("خطا در دریافت لیست داروها.")
            return ConversationHandler.END
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in edit_drugs: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
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
                    
                    context.user_data['editing_drug'] = dict(drug)
                    
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
    """Save drug edit changes"""
    await clear_conversation_state(update, context, silent=True)
    try:
        edit_field = context.user_data.get('edit_field')
        new_value = update.message.text
        drug = context.user_data.get('editing_drug')
        
        if not edit_field or not drug:
            await update.message.reply_text("خطا در ویرایش. لطفا دوباره تلاش کنید.")
            return ConversationHandler.END
        
        if edit_field == 'quantity':
            try:
                new_value = int(new_value)
                if new_value <= 0:
                    await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید.")
                    return States.EDIT_DRUG
            except ValueError:
                await update.message.reply_text("لطفا یک عدد صحیح وارد کنید.")
                return States.EDIT_DRUG
        elif edit_field == 'date':
            if not re.match(r'^\d{4}/\d{2}/\d{2}$', new_value):
                await update.message.reply_text("فرمت تاریخ نامعتبر است. لطفا به صورت 1403/05/15 وارد کنید.")
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
                
                await update.message.reply_text(
                    f"✅ ویرایش با موفقیت انجام شد!\n\n"
                    f"فیلد {edit_field} به {new_value} تغییر یافت."
                )
                
                # Update context
                drug[edit_field] = new_value
                
        except Exception as e:
            logger.error(f"Error updating drug: {e}")
            await update.message.reply_text("خطا در ویرایش دارو. لطفا دوباره تلاش کنید.")
        finally:
            if conn:
                conn.close()
        
        # Show edit menu again
        keyboard = [
            [InlineKeyboardButton("✏️ ویرایش تاریخ", callback_data="edit_date")],
            [InlineKeyboardButton("✏️ ویرایش تعداد", callback_data="edit_quantity")],
            [InlineKeyboardButton("🗑️ حذف دارو", callback_data="delete_drug")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_list")]
        ]
        
        await update.message.reply_text(
            f"ویرایش دارو:\n\n"
            f"تاریخ انقضا: {drug['date']}\n"
            f"تعداد: {drug['quantity']}\n\n"
            "لطفا گزینه مورد نظر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard))
        return States.EDIT_DRUG
    except Exception as e:
        logger.error(f"Error in save_drug_edit: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
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
        
        # ایجاد دکمه برای جستجوی اینلاین برای نیاز
        keyboard = [
            [InlineKeyboardButton(
                "🔍 جستجوی دارو برای نیاز", 
                switch_inline_query_current_chat="need "
            )],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
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
async def handle_need_drug_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback for need drug selection from inline query"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data.startswith("need_drug_"):
            idx = int(query.data.split("_")[2])
            if 0 <= idx < len(drug_list):
                selected_drug = drug_list[idx]
                context.user_data['need_drug'] = {
                    'name': selected_drug[0],
                    'price': selected_drug[1]
                }
                
                # حذف inline keyboard و نمایش پیام جدید
                await query.edit_message_text(
                    f"✅ داروی مورد نیاز انتخاب شد: {selected_drug[0]}\n💰 قیمت مرجع: {selected_drug[1]}\n\n"
                    "📝 لطفا توضیحاتی درباره این نیاز وارد کنید (اختیاری):",
                    reply_markup=None
                )
                return States.ADD_NEED_DESC
                
    except Exception as e:
        logger.error(f"Error handling need drug callback: {e}")
        await query.edit_message_text("خطا در انتخاب دارو. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
async def handle_need_drug_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drug selection for need from inline query"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data.startswith("need_drug_"):
            idx = int(query.data.split("_")[2])
            if 0 <= idx < len(drug_list):
                selected_drug = drug_list[idx]
                context.user_data['need_drug'] = {
                    'name': selected_drug[0],
                    'price': selected_drug[1]
                }
                
                await query.edit_message_text(
                    f"✅ داروی مورد نیاز انتخاب شد: {selected_drug[0]}\n💰 قیمت مرجع: {selected_drug[1]}\n\n"
                    "📝 لطفا توضیحاتی درباره این نیاز وارد کنید (اختیاری):"
                )
                return States.ADD_NEED_DESC
                
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
        await update.message.reply_text("لطفا تعداد مورد نیاز را وارد کنید:")
        return States.ADD_NEED_QUANTITY
    except Exception as e:
        logger.error(f"Error in save_need_desc: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
async def save_need(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save need to database with selected drug"""
    await clear_conversation_state(update, context, silent=True)
    try:
        try:
            quantity = int(update.message.text)
            if quantity <= 0:
                await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید.")
                return States.ADD_NEED_QUANTITY
            
            # دریافت اطلاعات دارو از context
            need_drug = context.user_data.get('need_drug', {})
            drug_name = need_drug.get('name', '')
            drug_price = need_drug.get('price', '')
            
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor() as cursor:
                    cursor.execute('''
                    INSERT INTO user_needs (
                        user_id, name, description, quantity, reference_price
                    ) VALUES (%s, %s, %s, %s, %s)
                    ''', (
                        update.effective_user.id,
                        drug_name,  # استفاده از نام دارو از اکسل
                        context.user_data.get('need_desc', ''),
                        quantity,
                        drug_price  # ذخیره قیمت مرجع
                    ))
                    conn.commit()
                    
                    await update.message.reply_text(
                        f"✅ نیاز شما با موفقیت ثبت شد!\n\n"
                        f"نام: {drug_name}\n"
                        f"قیمت مرجع: {drug_price}\n"
                        f"توضیحات: {context.user_data.get('need_desc', 'بدون توضیح')}\n"
                        f"تعداد: {quantity}"
                    )
                    
                    # Check for matches with other users' drugs
                    context.application.create_task(check_for_matches(update.effective_user.id, context))
                    
            except Exception as e:
                logger.error(f"Error saving need: {e}")
                await update.message.reply_text("خطا در ثبت نیاز. لطفا دوباره تلاش کنید.")
            finally:
                if conn:
                    conn.close()
            
            return ConversationHandler.END
            
        except ValueError:
            await update.message.reply_text("لطفا یک عدد صحیح وارد کنید.")
            return States.ADD_NEED_QUANTITY
    except Exception as e:
        logger.error(f"Error in save_need: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
async def list_my_needs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست نیازهای کاربر بدون پیام لغو"""
    try:
        # پاک کردن stateهای قبلی (بی صدا)
        await clear_conversation_state(update, context, silent=True)
        
        await ensure_user(update, context)
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT id, name, description, quantity 
                FROM user_needs 
                WHERE user_id = %s
                ORDER BY created_at DESC
                ''', (update.effective_user.id,))
                needs = cursor.fetchall()
                
                if needs:
                    message = "📝 لیست نیازهای شما:\n\n"
                    for need in needs:
                        message += (
                            f"• {need['name']}\n"
                            f"  توضیحات: {need['description'] or 'بدون توضیح'}\n"
                            f"  تعداد: {need['quantity']}\n\n"
                        )
                    
                    keyboard = [
                        [InlineKeyboardButton("✏️ ویرایش نیازها", callback_data="edit_needs")],
                        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_main")]
                    ]
                    
                    await update.message.reply_text(
                        message,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    return States.EDIT_NEED
                else:
                    await update.message.reply_text("شما هنوز هیچ نیازی ثبت نکرده‌اید.")
                    
        except Exception as e:
            logger.error(f"Error listing needs: {e}")
            await update.message.reply_text("خطا در دریافت لیست نیازها.")
        finally:
            if conn:
                conn.close()
                
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in list_my_needs: {e}")
        return ConversationHandler.END

async def edit_needs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start needs editing process"""
    await clear_conversation_state(update, context, silent=True)
    try:
        query = update.callback_query
        await query.answer()

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
                
                if not needs:
                    await query.edit_message_text("هیچ نیازی برای ویرایش وجود ندارد.")
                    return ConversationHandler.END
                
                keyboard = []
                for need in needs:
                    keyboard.append([InlineKeyboardButton(
                        f"{need['name']} ({need['quantity']})",
                        callback_data=f"edit_need_{need['id']}"
                    )])
                
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back")])
                
                await query.edit_message_text(
                    "لطفا نیازی که می‌خواهید ویرایش کنید را انتخاب کنید:",
                    reply_markup=InlineKeyboardMarkup(keyboard))
                return States.EDIT_NEED
                
        except Exception as e:
            logger.error(f"Error in edit_needs: {e}")
            await query.edit_message_text("خطا در دریافت لیست نیازها.")
            return ConversationHandler.END
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in edit_needs: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def edit_need_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit specific need item"""
    await clear_conversation_state(update, context, silent=True)
    try:
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
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
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
    """Save need edit changes"""
    await clear_conversation_state(update, context, silent=True)
    try:
        edit_field = context.user_data.get('edit_field')
        new_value = update.message.text
        need = context.user_data.get('editing_need')
        
        if not edit_field or not need:
            await update.message.reply_text("خطا در ویرایش. لطفا دوباره تلاش کنید.")
            return ConversationHandler.END

        if edit_field == 'quantity':
            try:
                new_value = int(new_value)
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
                    f"فیلد {edit_field} به {new_value} تغییر یافت."
                )
                
                # Update context
                need[edit_field] = new_value
                
        except Exception as e:
            logger.error(f"Error updating need: {e}")
            await update.message.reply_text("خطا در ویرایش نیاز. لطفا دوباره تلاش کنید.")
        finally:
            if conn:
                conn.close()
        
        # Show edit menu again
        keyboard = [
            [InlineKeyboardButton("✏️ ویرایش نام", callback_data="edit_need_name")],
            [InlineKeyboardButton("✏️ ویرایش توضیحات", callback_data="edit_need_desc")],
            [InlineKeyboardButton("✏️ ویرایش تعداد", callback_data="edit_need_quantity")],
            [InlineKeyboardButton("🗑️ حذف نیاز", callback_data="delete_need")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_needs_list")]
        ]
        
        await update.message.reply_text(
            f"ویرایش نیاز:\n\n"
            f"نام: {need['name']}\n"
            f"توضیحات: {need['description'] or 'بدون توضیح'}\n"
            f"تعداد: {need['quantity']}\n\n"
            "لطفا گزینه مورد نظر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard))
        return States.EDIT_NEED
    except Exception as e:
        logger.error(f"Error in save_need_edit: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
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
    """Start drug search process"""
    await clear_conversation_state(update, context, silent=True)
    try:
        await update.message.reply_text(
            "لطفا نام داروی مورد نظر را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
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
                    # ایجاد کیبورد با دکمه بازگشت
                    keyboard = [
                        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_main")]
                    ]
                    
                    await update.message.reply_text(
                        "⚠️ هیچ داروخانه‌ای با این دارو پیدا نشد.",
                        reply_markup=InlineKeyboardMarkup(keyboard)
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
                        message += f"  💊 {drug['drug_name']} - {drug['price']} - {drug['quantity']} عدد\n"
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

                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back")])

                await update.message.reply_text(
                    message,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return States.SELECT_PHARMACY
                
        except Exception as e:
            logger.error(f"Database error in handle_search: {e}")
            await update.message.reply_text("خطا در جستجو.")
        finally:
            if conn:
                conn.close()
                
    except Exception as e:
        logger.error(f"Error in handle_search: {e}")
        await update.message.reply_text("خطایی در پردازش جستجو رخ داد.")
        return ConversationHandler.END
async def select_pharmacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pharmacy selection and initiate drug selection"""
    await clear_conversation_state(update, context, silent=True)
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
    await clear_conversation_state(update, context, silent=True)
    
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
                    message += f"{i}. {drug['name']} - {drug['price']} - {drug['quantity']} عدد\n"
                
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
                
                # ساخت کیبورد
                keyboard = []
                
                # دکمه‌های انتخاب دارو
                drug_buttons = []
                prefix = '💊' if current_list_type == 'mine' else '📌'
                for i, drug in enumerate(drugs, 1):
                    drug_buttons.append(KeyboardButton(f"{prefix} {i} - {drug['name']}"))
                if drug_buttons:
                    keyboard.append(drug_buttons)
                
                # دکمه‌های صفحه‌بندی
                pagination_row = []
                if page > 0:
                    pagination_row.append(KeyboardButton(f"{prefix} صفحه قبل"))
                if (page + 1) * items_per_page < total_items:
                    pagination_row.append(KeyboardButton(f"{prefix} صفحه بعد"))
                
                # دکمه‌های جابجایی بین لیست‌ها
                if current_list_type == 'mine':
                    pagination_row.append(KeyboardButton("📌 داروهای داروخانه هدف"))
                else:
                    pagination_row.append(KeyboardButton("💊 داروهای شما"))
                
                if pagination_row:
                    keyboard.append(pagination_row)
                
                # دکمه‌های عملیاتی
                action_buttons = []
                if offer_items or comp_items:
                    action_buttons.append(KeyboardButton("✅ اتمام انتخاب"))
                action_buttons.append(KeyboardButton("🔙 بازگشت به داروخانه‌ها"))
                
                if action_buttons:
                    keyboard.append(action_buttons)
                
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
    await clear_conversation_state(update, context, silent=True)
    try:
        selection = update.message.text
        current_list_type = context.user_data.get('current_list_type', 'mine')
        drugs = context.user_data.get(f'{current_list_type}_drugs', [])
        
        # مدیریت دکمه‌های خاص - این باید اول از همه بررسی شود
        if selection == "✅ اتمام انتخاب":
            return await handle_finish_selection(update, context)
        elif selection == "🔙 بازگشت به داروخانه‌ها":
            return await handle_back_button(update, context)
        
        # مدیریت دکمه‌های جابجایی و صفحه‌بندی
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
        
        # پردازش انتخاب دارو
        prefix = '💊' if current_list_type == 'mine' else '📌'
        if selection.startswith(prefix):
            try:
                parts = selection.split(" - ", 1)
                index_part = parts[0].replace(f"{prefix} ", "")
                index = int(index_part.split(" - ")[0]) - 1
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
                    
                    await update.message.reply_text(
                        f"💊 داروی انتخاب شده: {drug['name']}\n"
                        f"💰 قیمت: {drug['price']}\n"
                        f"📅 تاریخ انقضا: {drug['date']}\n"
                        f"📦 موجودی: {drug['quantity']}\n\n"
                        f"لطفا تعداد مورد نظر را وارد کنید:",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    return States.SELECT_QUANTITY
            except (ValueError, IndexError):
                pass
        
        # انتخاب نامعتبر
        await update.message.reply_text("لطفا یک گزینه معتبر انتخاب کنید.")
        return States.SELECT_DRUGS
        
    except Exception as e:
        logger.error(f"Error in handle_drug_selection_from_keyboard: {e}")
        await update.message.reply_text("خطا در پردازش انتخاب")
    return States.SELECT_DRUGS


async def enter_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive quantity for selected drug and show updated price difference"""
    await clear_conversation_state(update, context, silent=True)
    try:
        quantity = update.message.text.strip()
        current_selection = context.user_data.get('current_selection')
        
        if not current_selection:
            await update.message.reply_text("انتخاب دارو از دست رفته.")
            return await show_two_column_selection(update, context)
        
        try:
            quantity = int(quantity)
            if quantity <= 0 or quantity > current_selection['quantity']:
                await update.message.reply_text(
                    f"لطفا عددی بین 1 و {current_selection['quantity']} وارد کنید."
                )
                return States.SELECT_QUANTITY
        except ValueError:
            await update.message.reply_text("لطفا یک عدد معتبر وارد کنید.")
            return States.SELECT_QUANTITY
        
        # Add to appropriate list
        if current_selection['type'] == 'target':
            if 'offer_items' not in context.user_data:
                context.user_data['offer_items'] = []
            context.user_data['offer_items'].append({
                'drug_id': current_selection['id'],
                'drug_name': current_selection['name'],
                'price': current_selection['price'],
                'quantity': quantity,
                'pharmacy_id': context.user_data['selected_pharmacy_id']
            })
            list_type = "درخواستی"
        else:
            if 'comp_items' not in context.user_data:
                context.user_data['comp_items'] = []
            context.user_data['comp_items'].append({
                'id': current_selection['id'],
                'name': current_selection['name'],
                'price': current_selection['price'],
                'quantity': quantity
            })
            list_type = "جبرانی"
        
        # Calculate updated totals
        offer_items = context.user_data.get('offer_items', [])
        comp_items = context.user_data.get('comp_items', [])
        offer_total = sum(parse_price(item['price']) * item['quantity'] for item in offer_items)
        comp_total = sum(parse_price(item['price']) * item['quantity'] for item in comp_items)
        price_difference = offer_total - comp_total
        
        await update.message.reply_text(
            f"✅ {quantity} عدد از {current_selection['name']} به لیست {list_type} اضافه شد.\n\n"
            f"📊 خلاصه فعلی:\n"
            f"جمع درخواستی: {format_price(offer_total)}\n"
            f"جمع جبرانی: {format_price(comp_total)}\n"
            f"اختلاف قیمت: {format_price(price_difference)}",
            reply_markup=ReplyKeyboardRemove()
        )
        
        # Return to drug list
        return await show_two_column_selection(update, context)
        
    except Exception as e:
        logger.error(f"Error in enter_quantity: {e}")
        await update.message.reply_text("خطا در ثبت تعداد")
    return States.SELECT_QUANTITY

                


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
    """ارسال پیام به صورت ایمن برای هر دو نوع update"""
    await clear_conversation_state(update, context, silent=True)
    try:
        if update.callback_query:
            # برای callback query، پیام جدید ارسال می‌کنیم
            await context.bot.send_message(
                chat_id=update.callback_query.message.chat_id,
                text=text,
                reply_markup=reply_markup
            )
            # پیام callback را حذف یا edit می‌کنیم
            try:
                await update.callback_query.delete_message()
            except:
                try:
                    await update.callback_query.edit_message_text("✅")
                except:
                    pass
        else:
            # برای message معمولی
            await update.message.reply_text(
                text,
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Error in safe_reply: {e}")
        
        
                
    
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
            for item in comp_items:
                message += f"- {item['name']} ({item['quantity']} عدد) - {item['price']}\n"
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
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_selection")])
        
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
                            message += f"- {drug['name']} ({drug['quantity']} عدد) - {drug['price']}\n"
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
                    offer_message += f"- {item['drug_name']} ({item['quantity']} عدد) - {item['price']}\n"
                offer_message += f"\n💰 جمع کل درخواستی: {format_price(offer_total)}\n"
                
                offer_message += "\n📌 داروهای جبرانی:\n"
                for item in comp_items:
                    offer_message += f"- {item['name']} ({item['quantity']} عدد) - {item['price']}\n"
                offer_message += f"\n💰 جمع کل جبرانی: {format_price(comp_total)}\n"
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
    """Log errors and handle them gracefully"""
    try:
        logger.error(msg="Exception while handling update:", exc_info=context.error)
        
        if update and update.effective_user:
            error_message = (
                "⚠️ خطایی در پردازش درخواست شما رخ داد.\n\n"
                "لطفا دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
            )
            
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=error_message
                )
                await clear_conversation_state(update, context, silent=True)
            except:
                pass
            
            # Notify admin
            tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
            tb_string = ''.join(tb_list)
            
            admin_message = (
                f"⚠️ خطا برای کاربر {update.effective_user.id}:\n\n"
                f"{context.error}\n\n"
                f"Traceback:\n<code>{html.escape(tb_string)}</code>"
            )
            
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=admin_message,
                    parse_mode=ParseMode.HTML
                )
            except:
                pass
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
    """مدیریت تغییر فاز بین عملیات مختلف بدون نمایش پیام لغو"""
    try:
        text = update.message.text
        
        # ابتدا state فعلی را کاملاً پاک کنید (بی صدا)
        await clear_conversation_state(update, context, silent=True)
        
        # سپس عملیات جدید را شروع کنید
        if text == 'ساخت کد پرسنل':
            return await generate_personnel_code(update, context)
        elif text == 'جستجوی دارو':
            return await search_drug(update, context)
        elif text == 'اضافه کردن دارو':
            return await add_drug_item(update, context)
        elif text == 'لیست داروهای من':
            return await list_my_drugs(update, context)
        elif text == 'ثبت نیاز جدید':
            return await add_need(update, context)
        elif text == 'لیست نیازهای من':
            return await list_my_needs(update, context)
        elif text == 'تنظیم شاخه‌های دارویی':
            return await setup_medical_categories(update, context)
        else:
            # اگر گزینه نامعتبر بود، فقط منو را نشان دهد
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
        logger.error(f"Error in handle_state_change: {e}")
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
                    MessageHandler(filters.CONTACT | filters.TEXT, receive_phone_for_admin_verify)
                ]
            },
            fallbacks=[CommandHandler('cancel', clear_conversation_state)],  # تغییر fallback
            allow_reentry=True
        )
        
        # Registration handler (normal registration)
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
                    MessageHandler(filters.ALL & ~(filters.PHOTO | filters.Document.IMAGE), 
                                 lambda u, c: u.message.reply_text("لطفا تصویر کارت ملی را ارسال کنید."))
                ],
                States.REGISTER_LICENSE: [
                    MessageHandler(filters.PHOTO | filters.Document.IMAGE, register_medical_card),
                    MessageHandler(filters.ALL & ~(filters.PHOTO | filters.Document.IMAGE), 
                                 lambda u, c: u.message.reply_text("لطفا تصویر پروانه داروخانه را ارسال کنید."))
                ],
                States.REGISTER_MEDICAL_CARD: [
                    MessageHandler(filters.PHOTO | filters.Document.IMAGE, register_phone),
                    MessageHandler(filters.ALL & ~(filters.PHOTO | filters.Document.IMAGE), 
                                 lambda u, c: u.message.reply_text("لطفا تصویر کارت نظام پزشکی را ارسال کنید."))
                ],
                States.REGISTER_PHONE: [
                    MessageHandler(filters.CONTACT | filters.TEXT, register_address)
                ],
                States.REGISTER_ADDRESS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, verify_code)
                ],
                States.VERIFICATION_CODE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complete_registration)
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
                    CallbackQueryHandler(add_drug_item, pattern="^back$")
                ],
                States.ADD_DRUG_DATE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, add_drug_date),
                    CallbackQueryHandler(search_drug_for_adding, pattern="^back_to_search$")
                ],
                States.ADD_DRUG_QUANTITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_drug_item),
                    CallbackQueryHandler(handle_back, pattern="^back$")
                ],
                States.EDIT_DRUG: [
                    CallbackQueryHandler(edit_drugs, pattern="^back_to_list$"),
                    CallbackQueryHandler(edit_drug_item, pattern="^edit_drug_"),
                    CallbackQueryHandler(handle_drug_edit_action, pattern="^(edit_date|edit_quantity|delete_drug)$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_drug_edit),
                    CallbackQueryHandler(handle_drug_deletion, pattern="^(confirm_delete|cancel_delete)$")
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
                CallbackQueryHandler(edit_needs, pattern="^edit_needs$"),
                CallbackQueryHandler(edit_need_item, pattern="^edit_need_"),
                CallbackQueryHandler(handle_need_edit_action, pattern="^(edit_need_name|edit_need_desc|edit_need_quantity|delete_need)$"),
                CallbackQueryHandler(handle_need_deletion, pattern="^(confirm_need_delete|cancel_need_delete)$"),
                CallbackQueryHandler(handle_need_drug_selection, pattern="^need_drug_") 
            ],
            states={
                States.SEARCH_DRUG_FOR_NEED: [
                    InlineQueryHandler(handle_inline_query),
                    CallbackQueryHandler(handle_need_drug_callback, pattern="^need_drug_"),
                    ChosenInlineResultHandler(handle_chosen_inline_result),
                    CallbackQueryHandler(add_need, pattern="^back$")
                    
                ],
                States.ADD_NEED_DESC: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_need_desc)
                ],
                States.ADD_NEED_QUANTITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_need)
                ],
                States.EDIT_NEED: [
                    CallbackQueryHandler(edit_needs, pattern="^back_to_needs_list$"),
                    CallbackQueryHandler(edit_need_item, pattern="^edit_need_"),
                    CallbackQueryHandler(handle_need_edit_action, pattern="^(edit_need_name|edit_need_desc|edit_need_quantity|delete_need)$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_need_edit),
                    CallbackQueryHandler(handle_need_deletion, pattern="^(confirm_need_delete|cancel_need_delete)$")
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
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search)
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
        application.add_handler(categories_handler)
        application.add_handler(admin_handler)
        application.add_handler(InlineQueryHandler(handle_inline_query))
        application.add_handler(ChosenInlineResultHandler(handle_chosen_inline_result))
        application.add_handler(MessageHandler(filters.Regex('^ساخت کد پرسنل$'), generate_personnel_code))
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
        application.add_handler(CallbackQueryHandler(handle_add_drug_callback, pattern="^add_drug_"))

        # Add error handler
        application.add_error_handler(error_handler)
        
        # Start the Bot
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.critical(f"Fatal error in main: {e}")
        raise

if __name__ == '__main__':
    main()
