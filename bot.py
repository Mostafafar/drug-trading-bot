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
    ChosenInlineResultHandler
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
    SELECT_ITEMS = auto()
    SELECT_QUANTITY = auto()
    CONFIRM_OFFER = auto()
    CONFIRM_TOTALS = auto()
    ADD_NEED_NAME = auto()
    ADD_NEED_DESC = auto()
    ADD_NEED_QUANTITY = auto()
    SEARCH_DRUG_FOR_ADDING = auto()
    SELECT_DRUG_FOR_ADDING = auto()
    COMPENSATION_SELECTION = auto()
    COMPENSATION_QUANTITY = auto()
    ADD_DRUG_DATE = auto()
    ADD_DRUG_QUANTITY = auto()
    ADMIN_UPLOAD_EXCEL = auto()
    EDIT_ITEM = auto()
    EDIT_DRUG = auto()
    EDIT_NEED = auto()
    SETUP_CATEGORIES = auto()
    PERSONNEL_VERIFICATION = auto()
    PERSONNEL_LOGIN = auto()

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
            # Users table
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
            
            # Pharmacies table
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
            
            # Drug items table
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
            
            # Medical categories table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS medical_categories (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE
            )''')
            
            # User categories junction table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_categories (
                user_id BIGINT REFERENCES users(id),
                category_id INTEGER REFERENCES medical_categories(id),
                PRIMARY KEY (user_id, category_id)
            )''')
            
            # Offers table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS offers (
                id SERIAL PRIMARY KEY,
                pharmacy_id BIGINT REFERENCES pharmacies(user_id),
                buyer_id BIGINT REFERENCES users(id),
                status TEXT DEFAULT 'pending',
                total_price NUMERIC,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Offer items table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS offer_items (
                id SERIAL PRIMARY KEY,
                offer_id INTEGER REFERENCES offers(id),
                drug_name TEXT,
                price TEXT,
                quantity INTEGER,
                item_type TEXT DEFAULT 'drug'
            )''')
            
            # Compensation items table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS compensation_items (
                id SERIAL PRIMARY KEY,
                offer_id INTEGER REFERENCES offers(id),
                drug_id INTEGER REFERENCES drug_items(id),
                quantity INTEGER
            )''')
            
            # User needs table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_needs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(id),
                name TEXT,
                description TEXT,
                quantity INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Match notifications table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS match_notifications (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(id),
                drug_id INTEGER REFERENCES drug_items(id),
                need_id INTEGER REFERENCES user_needs(id),
                similarity_score REAL,
                notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Admin settings table
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
            
            # Simple codes table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS simple_codes (
                code TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_by BIGINT[] DEFAULT array[]::BIGINT[],
                max_uses INTEGER DEFAULT 5
            )''')
            
            # Personnel codes table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS personnel_codes (
                code TEXT PRIMARY KEY,
                creator_id BIGINT REFERENCES pharmacies(user_id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )''')
            
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            
            # Insert default categories
            default_categories = ['اعصاب', 'قلب', 'ارتوپد', 'زنان', 'گوارش', 'پوست', 'اطفال']
            for category in default_categories:
                cursor.execute('''
                INSERT INTO medical_categories (name)
                VALUES (%s)
                ON CONFLICT (name) DO NOTHING
                ''', (category,))
            
            # Ensure admin user exists
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
    """Format text for Telegram button with proper line breaks"""
    if not text:
        return ""
    
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
        cleaned = ''.join(c for c in price_str if c.isdigit() or c in ['.', ','])
        cleaned = cleaned.replace(',', '')
        return float(cleaned)
    except ValueError:
        return 0.0

def format_price(price: float) -> str:
    """Format price with comma separators every 3 digits from right"""
    try:
        if price.is_integer():
            return "{:,}".format(int(price)).replace(",", "،")
        else:
            return "{:,.2f}".format(price).replace(",", "،")
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
            cursor.execute('''
            SELECT id, name, quantity 
            FROM user_needs 
            WHERE user_id = %s
            ''', (user_id,))
            needs = cursor.fetchall()
            
            if not needs:
                return
            
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
            
            matches = []
            for need in needs:
                for drug in drugs:
                    cursor.execute('''
                    SELECT id FROM match_notifications 
                    WHERE user_id = %s AND drug_id = %s AND need_id = %s
                    ''', (user_id, drug['id'], need['id']))
                    if cursor.fetchone():
                        continue
                    
                    sim_score = similarity(need['name'], drug['name'])
                    if sim_score >= 0.7:
                        matches.append({
                            'need': dict(need),
                            'drug': dict(drug),
                            'similarity': sim_score
                        })
            
            if not matches:
                return
            
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler with both registration options and verification check"""
    try:
        await ensure_user(update, context)
        
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

        context.application.create_task(check_for_matches(update.effective_user.id, context))
        
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
    
    except Exception as e:
        logger.error(f"Error in start handler: {e}")
        await update.message.reply_text(
            "خطایی در پردازش درخواست شما رخ داد. لطفاً دوباره تلاش کنید."
        )
        return ConversationHandler.END

async def generate_personnel_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate personnel code for verified pharmacies"""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('''
            SELECT 1 FROM pharmacies 
            WHERE user_id = %s AND verified = TRUE
            ''', (update.effective_user.id,))
            
            if not cursor.fetchone():
                await update.message.reply_text("❌ فقط داروخانه‌های تایید شده می‌توانند کد ایجاد کنند.")
                return

            code = str(random.randint(100000, 999999))
            
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
    """Start personnel login process"""
    try:
        query = update.callback_query
        await query.answer()
        
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

async def verify_personnel_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify personnel code"""
    try:
        code = update.message.text.strip()
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                SELECT creator_id FROM personnel_codes 
                WHERE code = %s
                ''', (code,))
                
                result = cursor.fetchone()
                if not result:
                    await update.message.reply_text("❌ کد نامعتبر است.")
                    return States.PERSONNEL_LOGIN
                    
                creator_id = result[0]
                
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

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Central callback query handler"""
    try:
        query = update.callback_query
        await query.answer()
        
        if not query.data:
            logger.warning("Empty callback data received")
            return

        if query.data.startswith("approve_user_"):
            return await approve_user(update, context)
        elif query.data.startswith("reject_user_"):
            return await reject_user(update, context)
        elif query.data.startswith("add_drug_"):
            return await handle_add_drug_callback(update, context)
        elif query.data == "back":
            return await handle_back(update, context)
        elif query.data == "cancel":
            return await cancel(update, context)
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

async def handle_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle back button with proper keyboard"""
    try:
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['تنظیم شاخه‌های دارویی', 'لیست داروهای من'],
            ['ثبت نیاز جدید', 'لیست نیازهای من']
        ]
        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            one_time_keyboard=True,
            resize_keyboard=True
        )
        
        try:
            await query.edit_message_text(
                "به منوی اصلی بازگشتید. لطفا یک گزینه را انتخاب کنید:",
                reply_markup=None
            )
        except:
            pass
            
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="به منوی اصلی بازگشتید. لطفا یک گزینه را انتخاب کنید:",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in handle_back: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="خطایی رخ داده است. به منوی اصلی بازگشتید."
        )
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
                cursor.execute('''
                UPDATE simple_codes 
                SET used_by = array_append(used_by, %s)
                WHERE code = %s AND array_length(used_by, 1) < max_uses
                RETURNING code
                ''', (update.effective_user.id, user_code))
                result = cursor.fetchone()
                
                if result:
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
    """Start admin verification process"""
    try:
        query = update.callback_query
        await query.answer()
        
        keyboard = [[KeyboardButton("اشتراک گذاری شماره تلفن", request_contact=True)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await query.edit_message_text(
            "لطفا برای تکمیل ثبت نام، شماره تلفن خود را با دکمه زیر به اشتراک بگذارید:",
            reply_markup=None
        )
        
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="لطفا شماره تلفن خود را به اشتراک بگذارید:",
            reply_markup=reply_markup
        )
        
        context.user_data['awaiting_phone'] = True
        return States.REGISTER_PHONE
        
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

async def receive_phone_for_admin_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive phone number for admin verification"""
    try:
        if update.message.contact:
            phone_number = update.message.contact.phone_number
        else:
            phone_number = update.message.text
        
        user = update.effective_user
        context.user_data['phone'] = phone_number
        
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
    """Approve user by admin"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = int(query.data.split("_")[2])
        logger.info(f"Starting approval process for user {user_id}")
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('SELECT id, is_verified FROM users WHERE id = %s', (user_id,))
                user_data = cursor.fetchone()
                
                if not user_data:
                    logger.error(f"User {user_id} not found")
                    await query.edit_message_text(f"❌ کاربر با آیدی {user_id} در سیستم ثبت نشده است")
                    return
                
                if user_data[1]:
                    logger.warning(f"User {user_id} already verified")
                    await query.edit_message_text(f"⚠️ کاربر {user_id} قبلاً تایید شده بود")
                    return
                
                cursor.execute('''
                UPDATE users 
                SET is_verified = TRUE, 
                    is_pharmacy_admin = TRUE,
                    verification_method = 'admin_approved'
                WHERE id = %s
                RETURNING id
                ''', (user_id,))
                
                if not cursor.fetchone():
                    logger.error(f"Error updating user {user_id}")
                    await query.edit_message_text("خطا در به‌روزرسانی وضعیت کاربر")
                    return
                
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
                    logger.error(f"Error registering pharmacy for user {user_id}")
                    await query.edit_message_text("خطا در ثبت اطلاعات داروخانه")
                    conn.rollback()
                    return
                
                conn.commit()
                logger.info(f"User {user_id} successfully approved")
                
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="✅ حساب شما توسط ادمین تایید شد!\n\n"
                             "شما اکنون می‌توانید از تمام امکانات مدیریت داروخانه استفاده کنید."
                    )
                except Exception as e:
                    logger.error(f"Failed to notify user {user_id}: {str(e)}")
                
                await query.edit_message_text(
                    f"✅ کاربر {user_id} با موفقیت تایید شد و به عنوان مدیر داروخانه تنظیم شد."
                )
                
        except Exception as e:
            logger.error(f"Error approving user {user_id}: {str(e)}")
            await query.edit_message_text(f"خطا در تایید کاربر: {str(e)}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
                
    except Exception as e:
        logger.error(f"System error in approve_user: {str(e)}")
        try:
            await query.edit_message_text("خطای سیستمی در پردازش درخواست")
        except:
            pass

async def reject_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reject user by admin"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = int(query.data.split("_")[2])
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                DELETE FROM pharmacies 
                WHERE user_id = %s AND verified = FALSE
                ''', (user_id,))
                
                conn.commit()
                
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

async def upload_excel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start Excel upload process for admin"""
    try:
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
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
            file = await context.bot.get_file(update.message.document.file_id)
            file_path = await download_file(file, "drug_prices", "admin")
            
            try:
                new_df = pd.read_excel(file_path, engine='openpyxl')
                
                column_mapping = {
                    'نام فارسی': 'name',
                    'قیمت واحد': 'price',
                    'name': 'name',
                    'price': 'price'
                }
                new_df = new_df.rename(columns=column_mapping)
                
                new_df = new_df[['name', 'price']].dropna()
                new_df['name'] = new_df['name'].astype(str).str.strip()
                new_df['price'] = new_df['price'].astype(str).str.strip()
                new_df = new_df.drop_duplicates()
                
                try:
                    existing_df = pd.read_excel(excel_file, engine='openpyxl')
                    existing_df = existing_df[['name', 'price']].dropna()
                    existing_df['name'] = existing_df['name'].astype(str).str.strip()
                    existing_df['price'] = existing_df['price'].astype(str).str.strip()
                except:
                    existing_df = pd.DataFrame(columns=['name', 'price'])
                
                merged_df = pd.concat([existing_df, new_df])
                merged_df['price'] = merged_df['price'].apply(parse_price)
                merged_df = merged_df.sort_values('price', ascending=False)
                merged_df = merged_df.drop_duplicates('name', keep='first')
                merged_df = merged_df.sort_values('name')
                
                merged_df.to_excel(excel_file, index=False, engine='openpyxl')
                
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

async def generate_simple_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a simple verification code (admin only)"""
    try:
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
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
        
        code = str(random.randint(10000, 99999))
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                INSERT INTO simple_codes (code, max_uses)
                VALUES (%s, %s)
                ON CONFLICT (code) DO UPDATE SET max_uses = EXCLUDED.max_uses
                ''', (code, 5))
                conn.commit()
                
                await update.message.reply_text(
                    f"✅ کد تایید ساده ایجاد شد:\n\n"
                    f"کد: {code}\n"
                    f"حداکثر استفاده: 5 کاربر\n\n"
                    "این کد را می‌توانید به دیگران بدهید تا بدون ثبت مدارک از ربات استفاده کنند."
                )
        except Exception as e:
            logger.error(f"Error generating simple code: {e}")
            await update.message.reply_text("خطا در ایجاد کد تایید.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in generate_simple_code: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")

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
                
                admin_code = str(random.randint(10000, 99999))
                cursor.execute('''
                UPDATE pharmacies 
                SET admin_code = %s
                WHERE user_id = %s
                ''', (admin_code, pharmacy_id))
                
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
    query = update.callback_query
    await query.answer("🔄 در حال به‌روزرسانی...")
    
    if not query.data or not query.data.startswith("togglecat_"):
        return
    
    conn = None
    try:
        category_id = int(query.data.split("_")[1])
        user_id = query.from_user.id
        
        conn = get_db_connection()
        with conn.cursor() as cursor:
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
            
            with conn.cursor(cursor_factory=extras.DictCursor) as dict_cursor:
                dict_cursor.execute('''
                SELECT mc.id, mc.name, 
                       EXISTS(SELECT 1 FROM user_categories uc 
                              WHERE uc.user_id = %s AND uc.category_id = mc.id) as selected
                FROM medical_categories mc
                ORDER BY mc.name
                ''', (user_id,))
                categories = dict_cursor.fetchall()
                
                keyboard = []
                row = []
                for cat in categories:
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
                
                keyboard.append([InlineKeyboardButton("💾 ذخیره تغییرات", callback_data="save_categories")])
                
                try:
                    await query.edit_message_reply_markup(
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception as e:
                    if "Message is not modified" in str(e):
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
    try:
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "✅ شاخه‌های دارویی شما با موفقیت به‌روزرسانی شد.",
            reply_markup=None
        )
        
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


async def add_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start process to add a drug item with inline query"""
    try:
        await ensure_user(update, context)
        
        keyboard = [
            [InlineKeyboardButton(
                "🔍 جستجوی دارو", 
                switch_inline_query_current_chat=""
            )],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
        ]
        
        await update.message.reply_text(
            "برای اضافه کردن دارو، روی دکمه جستجو کلیک کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.SEARCH_DRUG_FOR_ADDING
        
    except Exception as e:
        logger.error(f"Error in add_drug_item: {e}")
        await update.message.reply_text("خطایی در شروع فرآیند اضافه کردن دارو رخ داد.")
        return ConversationHandler.END

async def search_drug_for_adding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start drug search process for adding items"""
    try:
        keyboard = [
            [InlineKeyboardButton(
                "🔍 جستجوی دارو", 
                switch_inline_query_current_chat=""
            )],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
        ]
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "برای جستجوی دارو روی دکمه زیر کلیک کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                "برای جستجوی دارو روی دکمه زیر کلیک کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        return States.SEARCH_DRUG_FOR_ADDING
        
    except Exception as e:
        logger.error(f"Error in search_drug_for_adding: {e}")
        await update.message.reply_text("خطایی در شروع جستجو رخ داد.")
        return ConversationHandler.END


async def handle_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline queries for drug search"""
    try:
        query = update.inline_query.query
        if not query:
            return
        
        results = []
        for drug in drug_list[:50]:  # Limit to 50 results
            name, price = drug
            if query.lower() in name.lower():
                results.append(
                    InlineQueryResultArticle(
                        id=str(hash(name)),
                        title=name,
                        description=f"قیمت: {price}",
                        input_message_content=InputTextMessageContent(
                            f"داروی انتخاب شده: {name}\nقیمت: {price}"
                        )
                    )
                )
        
        await update.inline_query.answer(results)
    except Exception as e:
        logger.error(f"Error in handle_inline_query: {e}")

async def handle_chosen_inline_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle selected inline result for drug addition"""
    try:
        result = update.chosen_inline_result
        drug_info = result.result_id.split('|')
        
        if len(drug_info) == 2:
            drug_name, drug_price = drug_info
            context.user_data['selected_drug'] = {'name': drug_name, 'price': drug_price}
            
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=f"داروی انتخاب شده: {drug_name}\nقیمت: {drug_price}\n\nلطفا تاریخ انقضا را وارد کنید (مثال: 1403/06/15):",
                reply_markup=ReplyKeyboardRemove()
            )
            
            return States.ADD_DRUG_DATE
    except Exception as e:
        logger.error(f"Error in handle_chosen_inline_result: {e}")
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="خطایی در پردازش انتخاب دارو رخ داد. لطفا دوباره تلاش کنید."
        )
        return ConversationHandler.END

async def receive_drug_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive expiration date for drug item"""
    try:
        date = update.message.text.strip()
        if not re.match(r'^\d{4}/\d{2}/\d{2}$', date):
            await update.message.reply_text("فرمت تاریخ نامعتبر است. لطفا به صورت 1403/06/15 وارد کنید.")
            return States.ADD_DRUG_DATE
            
        context.user_data['selected_drug']['date'] = date
        
        await update.message.reply_text(
            "لطفا تعداد موجودی این دارو را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.ADD_DRUG_QUANTITY
    except Exception as e:
        logger.error(f"Error in receive_drug_date: {e}")
        await update.message.reply_text("خطایی در دریافت تاریخ رخ داد.")
        return ConversationHandler.END

async def receive_drug_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive quantity for drug item"""
    try:
        quantity = update.message.text.strip()
        if not quantity.isdigit() or int(quantity) <= 0:
            await update.message.reply_text("لطفا یک عدد صحیح مثبت وارد کنید.")
            return States.ADD_DRUG_QUANTITY
            
        drug_data = context.user_data['selected_drug']
        drug_name = drug_data['name']
        drug_price = drug_data['price']
        drug_date = drug_data['date']
        quantity = int(quantity)
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                INSERT INTO drug_items (user_id, name, price, date, quantity)
                VALUES (%s, %s, %s, %s, %s)
                ''', (
                    update.effective_user.id,
                    drug_name,
                    drug_price,
                    drug_date,
                    quantity
                ))
                conn.commit()
                
                await update.message.reply_text(
                    f"✅ داروی {drug_name} با موفقیت اضافه شد!\n\n"
                    f"تعداد: {quantity}\n"
                    f"تاریخ انقضا: {drug_date}\n"
                    f"قیمت: {drug_price}"
                )
                
                # Check for matches with other users' needs
                context.application.create_task(check_for_matches(update.effective_user.id, context))
                
        except Exception as e:
            logger.error(f"Error saving drug item: {e}")
            await update.message.reply_text("خطا در ذخیره دارو. لطفا دوباره تلاش کنید.")
        finally:
            if conn:
                conn.close()
            
        return await start(update, context)
    except Exception as e:
        logger.error(f"Error in receive_drug_quantity: {e}")
        await update.message.reply_text("خطایی در دریافت تعداد رخ داد.")
        return ConversationHandler.END

async def search_drug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start drug search process for exchange"""
    try:
        await update.message.reply_text(
            "لطفا نام داروی مورد نظر را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.SEARCH_DRUG
    except Exception as e:
        logger.error(f"Error in search_drug: {e}")
        await update.message.reply_text("خطایی در شروع جستجو رخ داد.")
        return ConversationHandler.END

async def find_drug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Find matching drugs for exchange"""
    try:
        search_term = update.message.text.strip()
        if not search_term:
            await update.message.reply_text("لطفا نام دارو را وارد کنید.")
            return States.SEARCH_DRUG
            
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT di.id, di.name, di.price, di.quantity, 
                       u.id as pharmacy_id, 
                       p.name as pharmacy_name
                FROM drug_items di
                JOIN users u ON di.user_id = u.id
                JOIN pharmacies p ON u.id = p.user_id
                WHERE di.name ILIKE %s AND di.user_id != %s AND di.quantity > 0
                ORDER BY similarity(di.name, %s) DESC
                LIMIT 10
                ''', (f'%{search_term}%', update.effective_user.id, search_term))
                
                drugs = cursor.fetchall()
                
                if not drugs:
                    await update.message.reply_text(
                        "دارویی با این نام یافت نشد. لطفا نام دیگری را امتحان کنید.",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    return States.SEARCH_DRUG
                
                keyboard = []
                for drug in drugs:
                    btn_text = f"{drug['name']} - {drug['pharmacy_name']} - موجودی: {drug['quantity']}"
                    keyboard.append([
                        InlineKeyboardButton(
                            btn_text,
                            callback_data=f"pharmacy_{drug['pharmacy_id']}_{drug['id']}"
                        )
                    ])
                
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back")])
                
                await update.message.reply_text(
                    "نتایج جستجو:\nلطفا داروخانه مورد نظر را انتخاب کنید:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                return States.SELECT_PHARMACY
                
        except Exception as e:
            logger.error(f"Error searching drugs: {e}")
            await update.message.reply_text("خطا در جستجوی داروها.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in find_drug: {e}")
        await update.message.reply_text("خطایی در جستجو رخ داد.")
        return ConversationHandler.END

async def select_pharmacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pharmacy selection for exchange"""
    try:
        query = update.callback_query
        await query.answer()
        
        if not query.data.startswith("pharmacy_"):
            return
        
        _, pharmacy_id, drug_id = query.data.split('_')
        pharmacy_id = int(pharmacy_id)
        drug_id = int(drug_id)
        
        context.user_data['selected_pharmacy'] = pharmacy_id
        context.user_data['selected_drug'] = drug_id
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT di.id, di.name, di.price, di.quantity, 
                       p.name as pharmacy_name
                FROM drug_items di
                JOIN pharmacies p ON di.user_id = p.user_id
                WHERE di.id = %s
                ''', (drug_id,))
                
                drug = cursor.fetchone()
                
                if not drug:
                    await query.edit_message_text("دارو یافت نشد.")
                    return
                
                context.user_data['current_drug'] = dict(drug)
                
                keyboard = [
                    [InlineKeyboardButton("➕ انتخاب این دارو", callback_data=f"add_drug_{drug_id}")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_search")]
                ]
                
                await query.edit_message_text(
                    f"داروخانه: {drug['pharmacy_name']}\n\n"
                    f"دارو: {drug['name']}\n"
                    f"قیمت: {drug['price']}\n"
                    f"موجودی: {drug['quantity']}\n\n"
                    "برای اضافه کردن به سبد تبادل، دکمه زیر را انتخاب کنید:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                return States.SELECT_DRUGS
                
        except Exception as e:
            logger.error(f"Error selecting pharmacy: {e}")
            await query.edit_message_text("خطا در انتخاب داروخانه.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in select_pharmacy: {e}")
        await update.callback_query.edit_message_text("خطایی در انتخاب رخ داد.")
        return ConversationHandler.END

async def handle_add_drug_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle adding a drug to exchange list"""
    try:
        query = update.callback_query
        await query.answer()
        
        if 'exchange_items' not in context.user_data:
            context.user_data['exchange_items'] = []
            
        drug_id = int(query.data.split('_')[2])
        drug_data = context.user_data['current_drug']
        
        # Check if already added
        for item in context.user_data['exchange_items']:
            if item['drug_id'] == drug_id:
                await query.answer("این دارو قبلاً اضافه شده است", show_alert=True)
                return
        
        context.user_data['exchange_items'].append({
            'drug_id': drug_id,
            'name': drug_data['name'],
            'price': drug_data['price'],
            'pharmacy_id': context.user_data['selected_pharmacy'],
            'quantity': 1  # Default quantity
        })
        
        keyboard = [
            [InlineKeyboardButton("➕ افزایش تعداد", callback_data=f"inc_{drug_id}")],
            [InlineKeyboardButton("➖ کاهش تعداد", callback_data=f"dec_{drug_id}")],
            [InlineKeyboardButton("✅ تایید و ادامه", callback_data="finish_selection")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_pharmacies")]
        ]
        
        await query.edit_message_text(
            f"دارو به سبد اضافه شد:\n\n"
            f"نام: {drug_data['name']}\n"
            f"قیمت: {drug_data['price']}\n"
            f"تعداد: 1\n\n"
            "می‌توانید تعداد را تغییر دهید یا ادامه دهید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return States.SELECT_ITEMS
    except Exception as e:
        logger.error(f"Error in handle_add_drug_callback: {e}")
        await query.edit_message_text("خطایی در اضافه کردن دارو رخ داد.")
        return ConversationHandler.END

async def show_two_column_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show exchange items in two columns for better UX"""
    try:
        query = update.callback_query
        await query.answer()
        
        if 'exchange_items' not in context.user_data or not context.user_data['exchange_items']:
            await query.edit_message_text("سبد تبادل شما خالی است.")
            return States.SEARCH_DRUG
            
        items = context.user_data['exchange_items']
        total = sum(parse_price(item['price']) * item['quantity'] for item in items)
        
        # Format items into two columns
        item_texts = []
        for i, item in enumerate(items, 1):
            item_text = (
                f"{i}. {item['name']}\n"
                f"   قیمت: {item['price']}\n"
                f"   تعداد: {item['quantity']}\n"
                f"   جمع: {format_price(parse_price(item['price']) * item['quantity'])}\n"
            )
            item_texts.append(item_text)
        
        # Split into two columns
        half = (len(item_texts) // 2
        col1 = item_texts[:half]
        col2 = item_texts[half:]
        
        # Create two-column layout
        message_lines = ["لیست داروهای انتخاب شده:\n"]
        for left, right in zip(col1, col2):
            message_lines.append(f"{left.ljust(40)}{right}")
        
        # Add any remaining items if odd number
        if len(item_texts) % 2 != 0:
            message_lines.append(col1[-1] if len(col1) > len(col2) else col2[-1])
        
        message_lines.append(f"\n💰 جمع کل: {format_price(total)} تومان")
        
        keyboard = [
            [InlineKeyboardButton("➕ داروی جدید", callback_data="back_to_pharmacies")],
            [InlineKeyboardButton("🔄 ویرایش موارد", callback_data="edit_selection")],
            [InlineKeyboardButton("🔁 جبرانی", callback_data="compensate")],
            [InlineKeyboardButton("✅ تایید نهایی", callback_data="confirm_totals")]
        ]
        
        await query.edit_message_text(
            "".join(message_lines),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return States.CONFIRM_OFFER
    except Exception as e:
        logger.error(f"Error in show_two_column_selection: {e}")
        await query.edit_message_text("خطایی در نمایش سبد تبادل رخ داد.")
        return ConversationHandler.END

async def handle_compensation_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle compensation item selection"""
    try:
        query = update.callback_query
        await query.answer()
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT id, name, price, quantity
                FROM drug_items
                WHERE user_id = %s AND quantity > 0
                ORDER BY name
                ''', (update.effective_user.id,))
                
                drugs = cursor.fetchall()
                
                if not drugs:
                    await query.edit_message_text("هیچ دارویی برای جبران ندارید.")
                    return States.CONFIRM_OFFER
                
                keyboard = []
                row = []
                for drug in drugs:
                    btn_text = f"{drug['name']} ({drug['quantity']})"
                    row.append(InlineKeyboardButton(
                        btn_text,
                        callback_data=f"comp_{drug['id']}"
                    ))
                    if len(row) == 2:
                        keyboard.append(row)
                        row = []
                
                if row:
                    keyboard.append(row)
                
                keyboard.append([
                    InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_totals"),
                    InlineKeyboardButton("✅ اتمام", callback_data="comp_finish")
                ])
                
                await query.edit_message_text(
                    "داروهای خود را برای جبران انتخاب کنید:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                return States.COMPENSATION_SELECTION
                
        except Exception as e:
            logger.error(f"Error getting compensation drugs: {e}")
            await query.edit_message_text("خطا در دریافت لیست داروها.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in handle_compensation_selection: {e}")
        await query.edit_message_text("خطایی در انتخاب جبرانی رخ داد.")
        return ConversationHandler.END

async def confirm_totals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show final confirmation before sending offer"""
    try:
        query = update.callback_query
        await query.answer()
        
        if 'exchange_items' not in context.user_data or not context.user_data['exchange_items']:
            await query.edit_message_text("سبد تبادل شما خالی است.")
            return States.SEARCH_DRUG
            
        items = context.user_data['exchange_items']
        total = sum(parse_price(item['price']) * item['quantity'] for item in items)
        
        # Calculate compensation if any
        comp_total = 0
        if 'compensation_items' in context.user_data:
            comp_items = context.user_data['compensation_items']
            comp_total = sum(parse_price(item['price']) * item['quantity'] for item in comp_items)
        
        difference = total - comp_total
        context.user_data['difference'] = difference
        
        message = ["جزئیات تبادل:\n\n📦 داروهای درخواستی:\n"]
        for item in items:
            message.append(
                f"- {item['name']} ({item['quantity']} عدد) - {item['price']}\n"
            )
        
        message.append(f"\n💰 جمع کل: {format_price(total)} تومان\n")
        
        if 'compensation_items' in context.user_data and context.user_data['compensation_items']:
            message.append("\n💊 داروهای جبرانی:\n")
            for item in context.user_data['compensation_items']:
                message.append(
                    f"- {item['name']} ({item['quantity']} عدد) - {item['price']}\n"
                )
            message.append(f"\n💰 جمع جبرانی: {format_price(comp_total)} تومان\n")
        
        message.append(f"\n🔢 مابه‌التفاوت: {format_price(abs(difference))} تومان\n")
        
        if difference > 0:
            message.append("\nشما باید مبلغ بالا را پرداخت کنید.")
        elif difference < 0:
            message.append("\nشما مبلغ بالا را دریافت خواهید کرد.")
        else:
            message.append("\nمبادله شما کاملاً برابر است.")
        
        keyboard = [
            [InlineKeyboardButton("✅ تایید و ارسال", callback_data="send_offer")],
            [InlineKeyboardButton("🔄 ویرایش", callback_data="back_to_items")]
        ]
        
        await query.edit_message_text(
            "".join(message),
            reply_markup=InlineKeyboardMarkup(keyboard)
            
        return States.CONFIRM_TOTALS
    except Exception as e:
        logger.error(f"Error in confirm_totals: {e}")
        await query.edit_message_text("خطایی در تایید نهایی رخ داد.")
        return ConversationHandler.END

async def send_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the final offer to the pharmacy"""
    try:
        query = update.callback_query
        await query.answer()
        
        if 'exchange_items' not in context.user_data or not context.user_data['exchange_items']:
            await query.edit_message_text("سبد تبادل شما خالی است.")
            return States.SEARCH_DRUG
            
        buyer_id = update.effective_user.id
        pharmacy_id = context.user_data['selected_pharmacy']
        items = context.user_data['exchange_items']
        total = sum(parse_price(item['price']) * item['quantity'] for item in items)
        
        comp_items = context.user_data.get('compensation_items', [])
        comp_total = sum(parse_price(item['price']) * item['quantity'] for item in comp_items)
        difference = context.user_data['difference']
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Create offer record
                cursor.execute('''
                INSERT INTO offers (pharmacy_id, buyer_id, total_price)
                VALUES (%s, %s, %s)
                RETURNING id
                ''', (pharmacy_id, buyer_id, total))
                
                offer_id = cursor.fetchone()[0]
                
                # Add offer items
                for item in items:
                    cursor.execute('''
                    INSERT INTO offer_items (offer_id, drug_name, price, quantity)
                    VALUES (%s, %s, %s, %s)
                    ''', (offer_id, item['name'], item['price'], item['quantity']))
                
                # Add compensation items if any
                for item in comp_items:
                    cursor.execute('''
                    INSERT INTO compensation_items (offer_id, drug_id, quantity)
                    VALUES (%s, %s, %s)
                    ''', (offer_id, item['drug_id'], item['quantity']))
                
                conn.commit()
                
                # Notify pharmacy
                try:
                    cursor.execute('SELECT name FROM users WHERE id = %s', (buyer_id,))
                    buyer_name = cursor.fetchone()[0]
                    
                    offer_msg = [
                        f"📬 درخواست تبادل جدید از {buyer_name}:\n\n",
                        "📦 داروهای درخواستی:\n"
                    ]
                    
                    for item in items:
                        offer_msg.append(f"- {item['name']} ({item['quantity']} عدد) - {item['price']}\n")
                    
                    offer_msg.append(f"\n💰 جمع کل: {format_price(total)} تومان\n")
                    
                    if comp_items:
                        offer_msg.append("\n💊 داروهای جبرانی:\n")
                        for item in comp_items:
                            offer_msg.append(f"- {item['name']} ({item['quantity']} عدد) - {item['price']}\n")
                        offer_msg.append(f"\n💰 جمع جبرانی: {format_price(comp_total)} تومان\n")
                    
                    offer_msg.append(f"\n🔢 مابه‌التفاوت: {format_price(abs(difference))} تومان\n")
                    
                    if difference > 0:
                        offer_msg.append(f"\nشما باید {format_price(difference)} تومان دریافت کنید.")
                    elif difference < 0:
                        offer_msg.append(f"\nشما باید {format_price(abs(difference))} تومان پرداخت کنید.")
                    else:
                        offer_msg.append("\nمبادله کاملاً برابر است.")
                    
                    keyboard = [
                        [
                            InlineKeyboardButton("✅ قبول", callback_data=f"offer_accept_{offer_id}"),
                            InlineKeyboardButton("❌ رد", callback_data=f"offer_reject_{offer_id}")
                        ]
                    ]
                    
                    await context.bot.send_message(
                        chat_id=pharmacy_id,
                        text="".join(offer_msg),
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception as e:
                    logger.error(f"Failed to notify pharmacy: {e}")
                
                await query.edit_message_text(
                    "✅ درخواست تبادل شما با موفقیت ارسال شد!\n\n"
                    "پس از بررسی توسط داروخانه، نتیجه به شما اطلاع داده خواهد شد."
                )
                
                # Clear user data
                context.user_data.pop('exchange_items', None)
                context.user_data.pop('compensation_items', None)
                context.user_data.pop('difference', None)
                
                return await start(update, context)
                
        except Exception as e:
            logger.error(f"Error saving offer: {e}")
            await query.edit_message_text("خطا در ارسال درخواست تبادل.")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in send_offer: {e}")
        await query.edit_message_text("خطایی در ارسال درخواست رخ داد.")
        return ConversationHandler.END

async def handle_offer_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pharmacy's response to an offer"""
    try:
        query = update.callback_query
        await query.answer()
        
        action, offer_id = query.data.split('_')[1:]
        offer_id = int(offer_id)
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                if action == 'accept':
                    cursor.execute('''
                    UPDATE offers 
                    SET status = 'accepted'
                    WHERE id = %s
                    RETURNING buyer_id, pharmacy_id, total_price
                    ''', (offer_id,))
                    
                    result = cursor.fetchone()
                    if not result:
                        await query.edit_message_text("درخواست یافت نشد.")
                        return
                    
                    buyer_id, pharmacy_id, total = result
                    
                    # Notify buyer
                    try:
                        await context.bot.send_message(
                            chat_id=buyer_id,
                            text=f"✅ درخواست تبادل شما توسط داروخانه پذیرفته شد!\n\n"
                                 f"مبلغ کل: {format_price(total)} تومان\n\n"
                                 f"لطفا برای هماهنگی بیشتر با داروخانه تماس بگیرید."
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify buyer: {e}")
                    
                    await query.edit_message_text(
                        "✅ درخواست تبادل را پذیرفتید.\n\n"
                        "خریدار مطلع شد. لطفا برای هماهنگی بیشتر با او در تماس باشید."
                    )
                    
                elif action == 'reject':
                    cursor.execute('''
                    UPDATE offers 
                    SET status = 'rejected'
                    WHERE id = %s
                    RETURNING buyer_id
                    ''', (offer_id,))
                    
                    buyer_id = cursor.fetchone()[0]
                    
                    # Notify buyer
                    try:
                        await context.bot.send_message(
                            chat_id=buyer_id,
                            text="❌ متاسفانه درخواست تبادل شما توسط داروخانه رد شد."
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify buyer: {e}")
                    
                    await query.edit_message_text(
                        "❌ درخواست تبادل را رد کردید.\n\n"
                        "خریدار مطلع شد."
                    )
                
                conn.commit()
        except Exception as e:
            logger.error(f"Error handling offer response: {e}")
            await query.edit_message_text("خطا در پردازش پاسخ.")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in handle_offer_response: {e}")
        await query.edit_message_text("خطایی در پردازش پاسخ رخ داد.")

async def add_need_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start process to add a need by getting name"""
    try:
        await update.message.reply_text(
            "لطفا نام داروی مورد نیاز را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.ADD_NEED_NAME
    except Exception as e:
        logger.error(f"Error in add_need_name: {e}")
        await update.message.reply_text("خطایی در شروع ثبت نیاز رخ داد.")
        return ConversationHandler.END

async def add_need_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get description for the need"""
    try:
        name = update.message.text.strip()
        if not name:
            await update.message.reply_text("لطفا نام معتبر وارد کنید.")
            return States.ADD_NEED_NAME
            
        context.user_data['need_name'] = name
        
        await update.message.reply_text(
            "لطفا توضیحات اضافی (مانند دوز، شرکت سازنده و ...) وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.ADD_NEED_DESC
    except Exception as e:
        logger.error(f"Error in add_need_desc: {e}")
        await update.message.reply_text("خطایی در دریافت نام رخ داد.")
        return ConversationHandler.END

async def add_need_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get quantity for the need"""
    try:
        desc = update.message.text.strip()
        context.user_data['need_desc'] = desc
        
        await update.message.reply_text(
            "لطفا تعداد مورد نیاز را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.ADD_NEED_QUANTITY
    except Exception as e:
        logger.error(f"Error in add_need_quantity: {e}")
        await update.message.reply_text("خطایی در دریافت توضیحات رخ داد.")
        return ConversationHandler.END

async def save_need(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save the need to database"""
    try:
        quantity = update.message.text.strip()
        if not quantity.isdigit() or int(quantity) <= 0:
            await update.message.reply_text("لطفا یک عدد صحیح مثبت وارد کنید.")
            return States.ADD_NEED_QUANTITY
            
        quantity = int(quantity)
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                INSERT INTO user_needs (user_id, name, description, quantity)
                VALUES (%s, %s, %s, %s)
                ''', (
                    update.effective_user.id,
                    context.user_data['need_name'],
                    context.user_data['need_desc'],
                    quantity
                ))
                conn.commit()
                
                await update.message.reply_text(
                    f"✅ نیاز شما با موفقیت ثبت شد!\n\n"
                    f"نام: {context.user_data['need_name']}\n"
                    f"توضیحات: {context.user_data['need_desc']}\n"
                    f"تعداد: {quantity}"
                )
                
                # Check for matches immediately
                context.application.create_task(check_for_matches(update.effective_user.id, context))
                
        except Exception as e:
            logger.error(f"Error saving need: {e}")
            await update.message.reply_text("خطا در ثبت نیاز.")
        finally:
            if conn:
                conn.close()
            
        return await start(update, context)
    except Exception as e:
        logger.error(f"Error in save_need: {e}")
        await update.message.reply_text("خطایی در ثبت نیاز رخ داد.")
        return ConversationHandler.END

async def list_my_drugs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List user's drug items"""
    try:
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT id, name, price, date, quantity
                FROM drug_items
                WHERE user_id = %s
                ORDER BY name
                ''', (update.effective_user.id,))
                
                drugs = cursor.fetchall()
                
                if not drugs:
                    await update.message.reply_text("هنوز دارویی اضافه نکرده‌اید.")
                    return
                
                message = ["لیست داروهای شما:\n\n"]
                for i, drug in enumerate(drugs, 1):
                    message.append(
                        f"{i}. {drug['name']}\n"
                        f"   قیمت: {drug['price']}\n"
                        f"   تاریخ: {drug['date']}\n"
                        f"   تعداد: {drug['quantity']}\n\n"
                    )
                
                keyboard = [[InlineKeyboardButton("✏️ ویرایش داروها", callback_data="edit_drugs")]]
                
                await update.message.reply_text(
                    "".join(message),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                
        except Exception as e:
            logger.error(f"Error listing drugs: {e}")
            await update.message.reply_text("خطا در دریافت لیست داروها.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in list_my_drugs: {e}")
        await update.message.reply_text("خطایی در نمایش داروها رخ داد.")

async def list_my_needs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List user's needs"""
    try:
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
                
                if not needs:
                    await update.message.reply_text("هنوز نیازی ثبت نکرده‌اید.")
                    return
                
                message = ["لیست نیازهای شما:\n\n"]
                for i, need in enumerate(needs, 1):
                    message.append(
                        f"{i}. {need['name']}\n"
                        f"   توضیحات: {need['description']}\n"
                        f"   تعداد: {need['quantity']}\n\n"
                    )
                
                keyboard = [[InlineKeyboardButton("✏️ ویرایش نیازها", callback_data="edit_needs")]]
                
                await update.message.reply_text(
                    "".join(message),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                
        except Exception as e:
            logger.error(f"Error listing needs: {e}")
            await update.message.reply_text("خطا در دریافت لیست نیازها.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in list_my_needs: {e}")
        await update.message.reply_text("خطایی در نمایش نیازها رخ داد.")

async def edit_drugs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show drug items for editing"""
    try:
        query = update.callback_query
        if query:
            await query.answer()
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT id, name, price, date, quantity
                FROM drug_items
                WHERE user_id = %s
                ORDER BY name
                ''', (update.effective_user.id,))
                
                drugs = cursor.fetchall()
                
                if not drugs:
                    msg = "هنوز دارویی اضافه نکرده‌اید."
                    if query:
                        await query.edit_message_text(msg)
                    else:
                        await update.message.reply_text(msg)
                    return
                
                keyboard = []
                for drug in drugs:
                    btn_text = f"{drug['name']} ({drug['quantity']})"
                    keyboard.append([InlineKeyboardButton(
                        btn_text,
                        callback_data=f"edit_drug_{drug['id']}"
                    )])
                
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back")])
                
                msg = "لطفا دارویی که می‌خواهید ویرایش کنید را انتخاب کنید:"
                if query:
                    await query.edit_message_text(
                        msg,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    await update.message.reply_text(
                        msg,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                
        except Exception as e:
            logger.error(f"Error listing drugs for edit: {e}")
            msg = "خطا در دریافت لیست داروها."
            if query:
                await query.edit_message_text(msg)
            else:
                await update.message.reply_text(msg)
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in edit_drugs: {e}")
        await (query.edit_message_text if query else update.message.reply_text)(
            "خطایی در نمایش داروها رخ داد.")

async def edit_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show options for editing a specific drug item"""
    try:
        query = update.callback_query
        await query.answer()
        
        drug_id = int(query.data.split('_')[2])
        context.user_data['edit_drug_id'] = drug_id
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT name, price, date, quantity
                FROM drug_items
                WHERE id = %s AND user_id = %s
                ''', (drug_id, update.effective_user.id))
                
                drug = cursor.fetchone()
                
                if not drug:
                    await query.edit_message_text("دارو یافت نشد.")
                    return
                
                keyboard = [
                    [InlineKeyboardButton("✏️ ویرایش تاریخ", callback_data="edit_date")],
                    [InlineKeyboardButton("✏️ ویرایش تعداد", callback_data="edit_quantity")],
                    [InlineKeyboardButton("🗑️ حذف دارو", callback_data="delete_drug")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_list")]
                ]
                
                await query.edit_message_text(
                    f"دارو: {drug['name']}\n"
                    f"قیمت: {drug['price']}\n"
                    f"تاریخ: {drug['date']}\n"
                    f"تعداد: {drug['quantity']}\n\n"
                    "لطفا عملیات مورد نظر را انتخاب کنید:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
        except Exception as e:
            logger.error(f"Error getting drug details: {e}")
            await query.edit_message_text("خطا در دریافت اطلاعات دارو.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in edit_drug_item: {e}")
        await query.edit_message_text("خطایی در نمایش دارو رخ داد.")

async def handle_drug_edit_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drug edit action selection"""
    try:
        query = update.callback_query
        await query.answer()
        
        action = query.data
        drug_id = context.user_data.get('edit_drug_id')
        
        if not drug_id:
            await query.edit_message_text("خطا در شناسایی دارو.")
            return await edit_drugs(update, context)
        
        if action == "edit_date":
            await query.edit_message_text(
                "لطفا تاریخ جدید را وارد کنید (مثال: 1403/06/15):",
                reply_markup=None
            )
            return States.EDIT_ITEM
        elif action == "edit_quantity":
            await query.edit_message_text(
                "لطفا تعداد جدید را وارد کنید:",
                reply_markup=None
            )
            return States.EDIT_ITEM
        elif action == "delete_drug":
            keyboard = [
                [InlineKeyboardButton("✅ بله، حذف کن", callback_data="confirm_delete")],
                [InlineKeyboardButton("❌ انصراف", callback_data="cancel_delete")]
            ]
            await query.edit_message_text(
                "آیا مطمئن هستید که می‌خواهید این دارو را حذف کنید؟",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return States.EDIT_ITEM
        else:
            await query.edit_message_text("عملیات نامعتبر.")
            return await edit_drug_item(update, context)
            
    except Exception as e:
        logger.error(f"Error in handle_drug_edit_action: {e}")
        await query.edit_message_text("خطایی در پردازش عملیات رخ داد.")
        return await edit_drugs(update, context)

async def update_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Update drug item based on user input"""
    try:
        drug_id = context.user_data.get('edit_drug_id')
        if not drug_id:
            await update.message.reply_text("خطا در شناسایی دارو.")
            return await edit_drugs(update, context)
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Get current drug info to determine which field we're updating
                cursor.execute('''
                SELECT name, date, quantity 
                FROM drug_items 
                WHERE id = %s AND user_id = %s
                ''', (drug_id, update.effective_user.id))
                drug = cursor.fetchone()
                
                if not drug:
                    await update.message.reply_text("دارو یافت نشد.")
                    return await edit_drugs(update, context)
                
                field = None
                value = update.message.text.strip()
                
                # Determine which field we're updating based on the current value
                if value == drug[1]:  # Date
                    field = 'date'
                elif value == str(drug[2]):  # Quantity
                    field = 'quantity'
                    if not value.isdigit() or int(value) < 0:
                        await update.message.reply_text("لطفا یک عدد صحیح مثبت وارد کنید.")
                        return States.EDIT_ITEM
                else:
                    # If not matching any current value, check format
                    if re.match(r'^\d{4}/\d{2}/\d{2}$', value):
                        field = 'date'
                    elif value.isdigit():
                        field = 'quantity'
                    else:
                        await update.message.reply_text("ورودی نامعتبر. لطفا دوباره تلاش کنید.")
                        return States.EDIT_ITEM
                
                if field:
                    cursor.execute(f'''
                    UPDATE drug_items 
                    SET {field} = %s 
                    WHERE id = %s
                    ''', (value, drug_id))
                    conn.commit()
                    
                    await update.message.reply_text("✅ تغییرات با موفقیت ذخیره شد.")
                else:
                    await update.message.reply_text("خطا در تشخیص فیلد برای به‌روزرسانی.")
                
                return await edit_drug_item(update, context)
                
        except Exception as e:
            logger.error(f"Error updating drug: {e}")
            await update.message.reply_text("خطا در به‌روزرسانی دارو.")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in update_drug_item: {e}")
        await update.message.reply_text("خطایی در به‌روزرسانی رخ داد.")
        return await edit_drugs(update, context)

async def handle_drug_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drug item deletion confirmation"""
    try:
        query = update.callback_query
        await query.answer()
        
        drug_id = context.user_data.get('edit_drug_id')
        if not drug_id:
            await query.edit_message_text("خطا در شناسایی دارو.")
            return await edit_drugs(update, context)
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                DELETE FROM drug_items 
                WHERE id = %s AND user_id = %s
                RETURNING name
                ''', (drug_id, update.effective_user.id))
                
                result = cursor.fetchone()
                if not result:
                    await query.edit_message_text("دارو یافت نشد.")
                    return
                
                conn.commit()
                await query.edit_message_text(f"✅ داروی {result[0]} با موفقیت حذف شد.")
                
        except Exception as e:
            logger.error(f"Error deleting drug: {e}")
            await query.edit_message_text("خطا در حذف دارو.")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
            
        return await edit_drugs(update, context)
    except Exception as e:
        logger.error(f"Error in handle_drug_deletion: {e}")
        await query.edit_message_text("خطایی در حذف دارو رخ داد.")
        return await edit_drugs(update, context)

async def edit_needs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show needs for editing"""
    try:
        query = update.callback_query
        if query:
            await query.answer()
        
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
                
                if not needs:
                    msg = "هنوز نیازی ثبت نکرده‌اید."
                    if query:
                        await query.edit_message_text(msg)
                    else:
                        await update.message.reply_text(msg)
                    return
                
                keyboard = []
                for need in needs:
                    btn_text = f"{need['name']} ({need['quantity']})"
                    keyboard.append([InlineKeyboardButton(
                        btn_text,
                        callback_data=f"edit_need_{need['id']}"
                    )])
                
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back")])
                
                msg = "لطفا نیازی که می‌خواهید ویرایش کنید را انتخاب کنید:"
                if query:
                    await query.edit_message_text(
                        msg,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                else:
                    await update.message.reply_text(
                        msg,
                        reply_markup=InlineKeyboardMarkup(keyboard))
                
        except Exception as e:
            logger.error(f"Error listing needs for edit: {e}")
            msg = "خطا در دریافت لیست نیازها."
            if query:
                await query.edit_message_text(msg)
            else:
                await update.message.reply_text(msg)
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in edit_needs: {e}")
        await (query.edit_message_text if query else update.message.reply_text)(
            "خطایی در نمایش نیازها رخ داد.")

async def edit_need_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show options for editing a specific need"""
    try:
        query = update.callback_query
        await query.answer()
        
        need_id = int(query.data.split('_')[2])
        context.user_data['edit_need_id'] = need_id
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT name, description, quantity
                FROM user_needs
                WHERE id = %s AND user_id = %s
                ''', (need_id, update.effective_user.id))
                
                need = cursor.fetchone()
                
                if not need:
                    await query.edit_message_text("نیاز یافت نشد.")
                    return
                
                keyboard = [
                    [InlineKeyboardButton("✏️ ویرایش نام", callback_data="edit_need_name")],
                    [InlineKeyboardButton("✏️ ویرایش توضیحات", callback_data="edit_need_desc")],
                    [InlineKeyboardButton("✏️ ویرایش تعداد", callback_data="edit_need_quantity")],
                    [InlineKeyboardButton("🗑️ حذف نیاز", callback_data="delete_need")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_needs_list")]
                ]
                
                await query.edit_message_text(
                    f"نیاز: {need['name']}\n"
                    f"توضیحات: {need['description']}\n"
                    f"تعداد: {need['quantity']}\n\n"
                    "لطفا عملیات مورد نظر را انتخاب کنید:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
        except Exception as e:
            logger.error(f"Error getting need details: {e}")
            await query.edit_message_text("خطا در دریافت اطلاعات نیاز.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in edit_need_item: {e}")
        await query.edit_message_text("خطایی در نمایش نیاز رخ داد.")

async def handle_need_edit_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle need edit action selection"""
    try:
        query = update.callback_query
        await query.answer()
        
        action = query.data
        need_id = context.user_data.get('edit_need_id')
        
        if not need_id:
            await query.edit_message_text("خطا در شناسایی نیاز.")
            return await edit_needs(update, context)
        
        if action in ["edit_need_name", "edit_need_desc", "edit_need_quantity"]:
            field_map = {
                "edit_need_name": "نام جدید",
                "edit_need_desc": "توضیحات جدید",
                "edit_need_quantity": "تعداد جدید"
            }
            context.user_data['edit_need_field'] = action
            await query.edit_message_text(
                f"لطفا {field_map[action]} را وارد کنید:",
                reply_markup=None
            )
            return States.EDIT_NEED
        elif action == "delete_need":
            keyboard = [
                [InlineKeyboardButton("✅ بله، حذف کن", callback_data="confirm_need_delete")],
                [InlineKeyboardButton("❌ انصراف", callback_data="cancel_need_delete")]
            ]
            await query.edit_message_text(
                "آیا مطمئن هستید که می‌خواهید این نیاز را حذف کنید؟",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return States.EDIT_NEED
        else:
            await query.edit_message_text("عملیات نامعتبر.")
            return await edit_need_item(update, context)
            
    except Exception as e:
        logger.error(f"Error in handle_need_edit_action: {e}")
        await query.edit_message_text("خطایی در پردازش عملیات رخ داد.")
        return await edit_needs(update, context)

async def update_need_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Update need item based on user input"""
    try:
        need_id = context.user_data.get('edit_need_id')
        field = context.user_data.get('edit_need_field')
        
        if not need_id or not field:
            await update.message.reply_text("خطا در شناسایی نیاز.")
            return await edit_needs(update, context)
        
        value = update.message.text.strip()
        
        if field == "edit_need_quantity":
            if not value.isdigit() or int(value) <= 0:
                await update.message.reply_text("لطفا یک عدد صحیح مثبت وارد کنید.")
                return States.EDIT_NEED
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                field_map = {
                    "edit_need_name": "name",
                    "edit_need_desc": "description",
                    "edit_need_quantity": "quantity"
                }
                
                cursor.execute(f'''
                UPDATE user_needs 
                SET {field_map[field]} = %s 
                WHERE id = %s AND user_id = %s
                ''', (value, need_id, update.effective_user.id))
                conn.commit()
                
                await update.message.reply_text("✅ تغییرات با موفقیت ذخیره شد.")
                
                # Check for new matches after update
                context.application.create_task(check_for_matches(update.effective_user.id, context))
                
        except Exception as e:
            logger.error(f"Error updating need: {e}")
            await update.message.reply_text("خطا در به‌روزرسانی نیاز.")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
            
        return await edit_need_item(update, context)
    except Exception as e:
        logger.error(f"Error in update_need_item: {e}")
        await update.message.reply_text("خطایی در به‌روزرسانی رخ داد.")
        return await edit_needs(update, context)

async def handle_need_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle need item deletion confirmation"""
    try:
        query = update.callback_query
        await query.answer()
        
        need_id = context.user_data.get('edit_need_id')
        if not need_id:
            await query.edit_message_text("خطا در شناسایی نیاز.")
            return await edit_needs(update, context)
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                DELETE FROM user_needs 
                WHERE id = %s AND user_id = %s
                RETURNING name
                ''', (need_id, update.effective_user.id))
                
                result = cursor.fetchone()
                if not result:
                    await query.edit_message_text("نیاز یافت نشد.")
                    return
                
                conn.commit()
                await query.edit_message_text(f"✅ نیاز {result[0]} با موفقیت حذف شد.")
                
        except Exception as e:
            logger.error(f"Error deleting need: {e}")
            await query.edit_message_text("خطا در حذف نیاز.")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
            
        return await edit_needs(update, context)
    except Exception as e:
        logger.error(f"Error in handle_need_deletion: {e}")
        await query.edit_message_text("خطایی در حذف نیاز رخ داد.")
        return await edit_needs(update, context)

async def handle_match_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user clicking on a match notification"""
    try:
        query = update.callback_query
        await query.answer()
        
        _, drug_id, need_id = query.data.split('_')
        drug_id = int(drug_id)
        need_id = int(need_id)
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                # Get drug details
                cursor.execute('''
                SELECT di.id, di.name, di.price, di.quantity, 
                       u.id as pharmacy_id, 
                       p.name as pharmacy_name
                FROM drug_items di
                JOIN users u ON di.user_id = u.id
                JOIN pharmacies p ON u.id = p.user_id
                WHERE di.id = %s
                ''', (drug_id,))
                drug = cursor.fetchone()
                
                # Get need details
                cursor.execute('''
                SELECT name, description, quantity
                FROM user_needs
                WHERE id = %s
                ''', (need_id,))
                need = cursor.fetchone()
                
                if not drug or not need:
                    await query.edit_message_text("اطلاعات یافت نشد.")
                    return
                
                context.user_data['selected_pharmacy'] = drug['pharmacy_id']
                context.user_data['selected_drug'] = drug['id']
                context.user_data['current_drug'] = dict(drug)
                
                message = (
                    "🔔 تطابق دارو با نیاز شما:\n\n"
                    f"نیاز شما: {need['name']}\n"
                    f"تعداد مورد نیاز: {need['quantity']}\n\n"
                    f"داروی موجود: {drug['name']}\n"
                    f"داروخانه: {drug['pharmacy_name']}\n"
                    f"قیمت: {drug['price']}\n"
                    f"موجودی: {drug['quantity']}\n\n"
                    "برای افزودن به سبد تبادل روی دکمه زیر کلیک کنید:"
                )
                
                keyboard = [
                    [InlineKeyboardButton("➕ افزودن به سبد تبادل", callback_data=f"add_drug_{drug_id}")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
                ]
                
                await query.edit_message_text(
                    message,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                return States.SELECT_DRUGS
                
        except Exception as e:
            logger.error(f"Error processing match: {e}")
            await query.edit_message_text("خطا در پردازش تطابق.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in handle_match_notification: {e}")
        await query.edit_message_text("خطایی در پردازش رخ داد.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation and return to main menu"""
    try:
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("عملیات لغو شد.")
        else:
            await update.message.reply_text("عملیات لغو شد.")
        
        return await start(update, context)
    except Exception as e:
        logger.error(f"Error in cancel: {e}")
        await update.message.reply_text("خطایی در لغو عملیات رخ داد.")
        return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors and handle them gracefully"""
    try:
        logger.error(f"Update {update} caused error {context.error}")
        
        if update and update.effective_user:
            user = update.effective_user
            error_msg = (
                f"⚠️ خطا در پردازش درخواست کاربر:\n\n"
                f"👤 کاربر: {user.full_name}\n"
                f"🆔 آیدی: {user.id}\n"
                f"📌 یوزرنیم: @{user.username or 'ندارد'}\n\n"
                f"💻 خطا:\n{context.error}"
            )
            
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=error_msg
                )
            except Exception as e:
                logger.error(f"Failed to send error to admin: {e}")
            
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="⚠️ خطایی در پردازش درخواست شما رخ داد. لطفاً دوباره تلاش کنید."
                )
            except Exception as e:
                logger.error(f"Failed to notify user: {e}")
    except Exception as e:
        logger.error(f"Error in error handler: {e}")

def main():
    """Start the bot"""
    load_drug_data()
    
    application = ApplicationBuilder() \
        .token("8447101535:AAFMFkqJeMFNBfhzrY1VURkfJI-vu766LrY") \
        .post_init(initialize_db) \
        .build()
    
    # Conversation handlers
    registration_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(register_pharmacy_name, pattern="^register$"),
            CallbackQueryHandler(admin_verify_start, pattern="^admin_verify$"),
            CallbackQueryHandler(personnel_login_start, pattern="^personnel_login$"),
            CallbackQueryHandler(simple_verify_start, pattern="^simple_verify$")
        ],
        states={
            States.START: [
                CallbackQueryHandler(register_pharmacy_name, pattern="^register$"),
                CallbackQueryHandler(admin_verify_start, pattern="^admin_verify$"),
                CallbackQueryHandler(personnel_login_start, pattern="^personnel_login$"),
                CallbackQueryHandler(simple_verify_start, pattern="^simple_verify$")
            ],
            States.REGISTER_PHARMACY_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_founder_name)
            ],
            States.REGISTER_FOUNDER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_national_card)
            ],
            States.REGISTER_NATIONAL_CARD: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, register_license)
            ],
            States.REGISTER_LICENSE: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, register_medical_card)
            ],
            States.REGISTER_MEDICAL_CARD: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, register_phone)
            ],
            States.REGISTER_PHONE: [
                MessageHandler(filters.CONTACT | filters.TEXT, register_address)
            ],
            States.REGISTER_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, verify_code)
            ],
            States.VERIFICATION_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, complete_registration)
            ],
            States.ADMIN_VERIFICATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone_for_admin_verify)
            ],
            States.SIMPLE_VERIFICATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, simple_verify_code)
            ],
            States.PERSONNEL_LOGIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, verify_personnel_code)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    drug_addition_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^اضافه کردن دارو$'), search_drug_for_adding)
        ],
        states={
            States.SEARCH_DRUG_FOR_ADDING: [
                CallbackQueryHandler(search_drug_for_adding, pattern="^back_to_search$"),
                CallbackQueryHandler(select_drug_for_adding, pattern="^select_drug_"),
                CallbackQueryHandler(cancel, pattern="^back$")
            ],
            States.SELECT_DRUG_FOR_ADDING: [
                CallbackQueryHandler(search_drug_for_adding, pattern="^back_to_search$"),
                CallbackQueryHandler(cancel, pattern="^back$")
            ],
            States.ADD_DRUG_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_drug_date)
            ],
            States.ADD_DRUG_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_drug_quantity)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    drug_search_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^جستجوی دارو$'), search_drug)
        ],
        states={
            States.SEARCH_DRUG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, find_drug)
            ],
            States.SELECT_PHARMACY: [
                CallbackQueryHandler(select_pharmacy, pattern="^pharmacy_"),
                CallbackQueryHandler(cancel, pattern="^back$")
            ],
            States.SELECT_DRUGS: [
                CallbackQueryHandler(handle_add_drug_callback, pattern="^add_drug_"),
                CallbackQueryHandler(cancel, pattern="^back$")
            ],
            States.SELECT_ITEMS: [
                CallbackQueryHandler(show_two_column_selection, pattern="^back_to_items$"),
                CallbackQueryHandler(confirm_totals, pattern="^finish_selection$"),
                CallbackQueryHandler(cancel, pattern="^back$")
            ],
            States.CONFIRM_OFFER: [
                CallbackQueryHandler(handle_compensation_selection, pattern="^compensate$"),
                CallbackQueryHandler(confirm_totals, pattern="^confirm_totals$"),
                CallbackQueryHandler(cancel, pattern="^back$")
            ],
            States.COMPENSATION_SELECTION: [
                CallbackQueryHandler(confirm_totals, pattern="^comp_finish$"),
                CallbackQueryHandler(cancel, pattern="^back$")
            ],
            States.CONFIRM_TOTALS: [
                CallbackQueryHandler(send_offer, pattern="^send_offer$"),
                CallbackQueryHandler(cancel, pattern="^back$")
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    need_addition_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^ثبت نیاز جدید$'), add_need_name)
        ],
        states={
            States.ADD_NEED_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_need_desc)
            ],
            States.ADD_NEED_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_need_quantity)
            ],
            States.ADD_NEED_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_need)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    edit_drugs_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(edit_drugs, pattern="^edit_drugs$")
        ],
        states={
            States.EDIT_ITEM: [
                CallbackQueryHandler(edit_drug_item, pattern="^cancel_delete$"),
                CallbackQueryHandler(handle_drug_deletion, pattern="^confirm_delete$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, update_drug_item)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    edit_needs_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(edit_needs, pattern="^edit_needs$")
        ],
        states={
            States.EDIT_NEED: [
                CallbackQueryHandler(edit_need_item, pattern="^cancel_need_delete$"),
                CallbackQueryHandler(handle_need_deletion, pattern="^confirm_need_delete$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, update_need_item)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    categories_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^تنظیم شاخه‌های دارویی$'), setup_medical_categories)
        ],
        states={
            States.SETUP_CATEGORIES: [
                CallbackQueryHandler(toggle_category, pattern="^togglecat_"),
                CallbackQueryHandler(save_categories, pattern="^save_categories$")
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    excel_upload_handler = ConversationHandler(
        entry_points=[
            CommandHandler("upload", upload_excel_start)
        ],
        states={
            States.ADMIN_UPLOAD_EXCEL: [
                MessageHandler(filters.Document.ALL | filters.TEXT, handle_excel_upload)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("generate_code", generate_simple_code))
    application.add_handler(CommandHandler("verify", verify_pharmacy))
    application.add_handler(registration_handler)
    application.add_handler(drug_addition_handler)
    application.add_handler(drug_search_handler)
    application.add_handler(need_addition_handler)
    application.add_handler(edit_drugs_handler)
    application.add_handler(edit_needs_handler)
    application.add_handler(categories_handler)
    application.add_handler(excel_upload_handler)
    
    # Inline query handlers
    application.add_handler(InlineQueryHandler(handle_inline_query))
    application.add_handler(ChosenInlineResultHandler(handle_chosen_inline_result))
    
    # Other handlers
    application.add_handler(MessageHandler(filters.Regex('^لیست داروهای من$'), list_my_drugs))
    application.add_handler(MessageHandler(filters.Regex('^لیست نیازهای من$'), list_my_needs))
    application.add_handler(MessageHandler(filters.Regex('^ساخت کد پرسنل$'), generate_personnel_code))
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    application.run_polling()

if __name__ == '__main__':
    main()
