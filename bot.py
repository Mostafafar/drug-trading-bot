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
    SELECT_QUANTITY = auto()
    CONFIRM_OFFER = auto()
    CONFIRM_TOTALS = auto()
    ADD_NEED_NAME = auto()
    ADD_NEED_DESC = auto()
    ADD_NEED_QUANTITY = auto()
    SEARCH_DRUG_FOR_ADDING = auto()
    CONFIRM_DRUG_SELECTION = auto()
    ENTER_EXPIRY_DATE = auto()
    ENTER_QUANTITY = auto()
    CONFIRM_ADD_DRUG = auto()
    COMPENSATION_SELECTION = auto()
    COMPENSATION_QUANTITY = auto()
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
            
            # Exchanges table
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

            # Exchange items table
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

            # Personnel codes table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS personnel_codes (
                code TEXT PRIMARY KEY,
                creator_id BIGINT REFERENCES pharmacies(user_id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )''')
            
            # Simple codes table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS simple_codes (
                code TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_by BIGINT[] DEFAULT array[]::BIGINT[],
                max_uses INTEGER DEFAULT 5
            )''')
            
            # Enable pg_trgm extension for similarity search
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
    """Format text for Telegram button display"""
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
    """Format price with comma separators"""
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

def validate_date(date_str: str) -> bool:
    """Validate date format (either YYYY/MM/DD or YYYY-MM-DD)"""
    return bool(re.match(r'^\d{4}[/-]\d{2}[/-]\d{2}$', date_str))

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

# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler with registration options and verification check"""
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
    
    except Exception as e:
        logger.error(f"Error in start handler: {e}")
        await update.message.reply_text(
            "خطایی در پردازش درخواست شما رخ داد. لطفاً دوباره تلاش کنید."
        )
        return ConversationHandler.END

async def generate_personnel_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate personnel code for pharmacy staff"""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Check if user is a verified pharmacy
            cursor.execute('''
            SELECT 1 FROM pharmacies 
            WHERE user_id = %s AND verified = TRUE
            ''', (update.effective_user.id,))
            
            if not cursor.fetchone():
                await update.message.reply_text("❌ فقط داروخانه‌های تایید شده می‌توانند کد ایجاد کنند.")
                return

            # Generate 6-digit code
            code = str(random.randint(100000, 999999))
            
            # Save code
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
    """Verify personnel login code"""
    try:
        code = update.message.text.strip()
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Verify the personnel code exists
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

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Central callback query handler"""
    try:
        query = update.callback_query
        await query.answer()
        
        if not query.data:
            logger.warning("Empty callback data received")
            return

        # Handle different callback patterns
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
        elif query.data == "confirm_drug":
            return await ask_for_expiry_date(update, context)
        elif query.data == "back_to_drug_confirmation":
            return await show_drug_confirmation(update, context)
        elif query.data == "back_to_date_entry":
            return await ask_for_expiry_date(update, context)
        elif query.data == "final_confirm":
            return await save_drug_item(update, context)
        elif query.data == "change_drug":
            return await search_drug_for_adding(update, context)
        
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
    """Start admin verification process"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Request phone number
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
        
        # Save phone number in database
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
        
        # Send info to admin with approve/reject buttons
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
        logger.info(f"Starting verification for user {user_id}")
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Check if user exists
                cursor.execute('SELECT id, is_verified FROM users WHERE id = %s', (user_id,))
                user_data = cursor.fetchone()
                
                if not user_data:
                    logger.error(f"User {user_id} not found")
                    await query.edit_message_text(f"❌ کاربر با آیدی {user_id} در سیستم ثبت نشده است")
                    return
                
                if user_data[1]:  # If user is already verified
                    logger.warning(f"User {user_id} is already verified")
                    await query.edit_message_text(f"⚠️ کاربر {user_id} قبلاً تایید شده بود")
                    return
                
                # Verify user
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
                
                # Create/update pharmacy
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
                logger.info(f"User {user_id} successfully verified")
                
                # Notify user
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
                # Remove user from verification queue
                cursor.execute('''
                DELETE FROM pharmacies 
                WHERE user_id = %s AND verified = FALSE
                ''', (user_id,))
                
                conn.commit()
                
                # Notify user
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
                    'name': 'name',
                    'price': 'price'
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

async def generate_simple_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a simple verification code (admin only)"""
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
        
        # Generate a 5-digit code
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
                
                # Add save button
                keyboard.append([InlineKeyboardButton("💾 ذخیره تغییرات", callback_data="save_categories")])
                
                # Faster edit with less waiting time
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
    """Setup medical categories selection interface"""
    try:
        conn = None
        try:
            user_id = update.effective_user.id
            conn = get_db_connection()
            
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                # Get all categories with user's selection status
                cursor.execute('''
                SELECT mc.id, mc.name, 
                       EXISTS(SELECT 1 FROM user_categories uc 
                              WHERE uc.user_id = %s AND uc.category_id = mc.id) as selected
                FROM medical_categories mc
                ORDER BY mc.name
                ''', (user_id,))
                categories = cursor.fetchall()
                
                # Build keyboard with visual indicators
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
                
                # Add save button
                keyboard.append([InlineKeyboardButton("💾 ذخیره تغییرات", callback_data="save_categories")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "لطفاً شاخه‌های دارویی مرتبط با داروخانه خود را انتخاب کنید:\n\n"
                    "🌟 = انتخاب شده\n"
                    "⚪ = انتخاب نشده",
                    reply_markup=reply_markup
                )
                return States.SETUP_CATEGORIES
                
        except Exception as e:
            logger.error(f"Error setting up categories: {e}")
            await update.message.reply_text("خطا در بارگذاری شاخه‌های دارویی")
            return ConversationHandler.END
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in setup_medical_categories: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

# Drug Management Handlers
async def search_drug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start drug search process"""
    try:
        await update.message.reply_text(
            "لطفا نام دارو را برای جستجو وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.SEARCH_DRUG
    except Exception as e:
        logger.error(f"Error in search_drug: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def handle_drug_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drug search query and show results"""
    try:
        search_query = update.message.text.strip()
        if not search_query or len(search_query) < 2:
            await update.message.reply_text("لطفا حداقل 2 حرف برای جستجو وارد کنید.")
            return States.SEARCH_DRUG
        
        # Search in drug list
        results = []
        for name, price in drug_list:
            if search_query.lower() in name.lower():
                results.append((name, price))
        
        if not results:
            await update.message.reply_text(
                "هیچ نتیجه‌ای یافت نشد. لطفا نام دیگری را امتحان کنید.",
                reply_markup=ReplyKeyboardRemove()
            )
            return States.SEARCH_DRUG
        
        # Limit to top 50 results
        results = results[:50]
        
        # Show results with pagination
        context.user_data['search_results'] = results
        context.user_data['current_page'] = 0
        
        await show_search_results(update, context)
        return States.SELECT_DRUGS
        
    except Exception as e:
        logger.error(f"Error in handle_drug_search: {e}")
        await update.message.reply_text("خطایی در جستجو رخ داد. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def show_search_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display paginated search results"""
    try:
        results = context.user_data.get('search_results', [])
        current_page = context.user_data.get('current_page', 0)
        items_per_page = 10
        total_pages = (len(results) + items_per_page - 1) // items_per_page
        
        if not results:
            await update.message.reply_text("هیچ نتیجه‌ای برای نمایش وجود ندارد.")
            return States.SEARCH_DRUG
        
        start_idx = current_page * items_per_page
        end_idx = min(start_idx + items_per_page, len(results))
        page_results = results[start_idx:end_idx]
        
        message = "نتایج جستجو:\n\n"
        for i, (name, price) in enumerate(page_results, start=1):
            message += f"{start_idx + i}. {name} - {price}\n"
        
        # Add pagination controls
        keyboard = []
        row = []
        
        # Add drug selection buttons (2 per row)
        for i, (name, price) in enumerate(page_results, start=1):
            btn_text = format_button_text(f"{start_idx + i}. {name}")
            row.append(InlineKeyboardButton(
                btn_text,
                callback_data=f"select_drug_{start_idx + i - 1}"
            ))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        
        if row:
            keyboard.append(row)
        
        # Add pagination navigation
        nav_buttons = []
        if current_page > 0:
            nav_buttons.append(InlineKeyboardButton("⏪ قبلی", callback_data="prev_page"))
        
        nav_buttons.append(InlineKeyboardButton(
            f"صفحه {current_page + 1}/{total_pages}",
            callback_data="current_page"
        ))
        
        if current_page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("بعدی ⏩", callback_data="next_page"))
        
        keyboard.append(nav_buttons)
        
        # Add back button
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_search")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text=message,
                    reply_markup=reply_markup
                )
            except:
                await update.callback_query.message.reply_text(
                    text=message,
                    reply_markup=reply_markup
                )
        else:
            await update.message.reply_text(
                text=message,
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logger.error(f"Error showing search results: {e}")
        await update.message.reply_text("خطایی در نمایش نتایج رخ داد.")

async def handle_search_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pagination for search results"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "next_page":
        context.user_data['current_page'] += 1
    elif query.data == "prev_page":
        context.user_data['current_page'] -= 1
    
    await show_search_results(update, context)
    return States.SELECT_DRUGS

async def select_drug_for_adding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drug selection from search results"""
    try:
        query = update.callback_query
        await query.answer()
        
        if not query.data.startswith("select_drug_"):
            return
        
        drug_idx = int(query.data.split("_")[2])
        results = context.user_data.get('search_results', [])
        
        if drug_idx < 0 or drug_idx >= len(results):
            await query.edit_message_text("خطا در انتخاب دارو. لطفا دوباره تلاش کنید.")
            return States.SEARCH_DRUG
        
        drug_name, drug_price = results[drug_idx]
        context.user_data['selected_drug'] = (drug_name, drug_price)
        
        # Show confirmation with drug details
        keyboard = [
            [InlineKeyboardButton("✅ تأیید", callback_data="confirm_drug")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_search")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"داروی انتخاب شده:\n\n"
            f"نام: {drug_name}\n"
            f"قیمت: {drug_price}\n\n"
            "آیا این دارو را تأیید می‌کنید؟",
            reply_markup=reply_markup
        )
        return States.CONFIRM_DRUG_SELECTION
        
    except Exception as e:
        logger.error(f"Error in select_drug_for_adding: {e}")
        await update.callback_query.edit_message_text("خطایی در انتخاب دارو رخ داد.")
        return States.SEARCH_DRUG

async def ask_for_expiry_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask user to enter expiry date for selected drug"""
    try:
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "لطفا تاریخ انقضای دارو را وارد کنید (فرمت: YYYY/MM/DD):",
            reply_markup=None
        )
        return States.ENTER_EXPIRY_DATE
        
    except Exception as e:
        logger.error(f"Error in ask_for_expiry_date: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return States.CONFIRM_DRUG_SELECTION

async def ask_for_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask user to enter quantity for selected drug"""
    try:
        expiry_date = update.message.text.strip()
        
        if not validate_date(expiry_date):
            await update.message.reply_text("فرمت تاریخ نامعتبر است. لطفا به فرمت YYYY/MM/DD وارد کنید.")
            return States.ENTER_EXPIRY_DATE
        
        context.user_data['expiry_date'] = expiry_date
        
        await update.message.reply_text(
            "لطفا تعداد موجودی این دارو را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.ENTER_QUANTITY
        
    except Exception as e:
        logger.error(f"Error in ask_for_quantity: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return States.ENTER_EXPIRY_DATE

async def confirm_add_drug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show confirmation before adding drug to inventory"""
    try:
        quantity = update.message.text.strip()
        
        try:
            quantity = int(quantity)
            if quantity <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("لطفا یک عدد صحیح مثبت وارد کنید.")
            return States.ENTER_QUANTITY
        
        context.user_data['quantity'] = quantity
        
        drug_name, drug_price = context.user_data['selected_drug']
        expiry_date = context.user_data['expiry_date']
        
        keyboard = [
            [InlineKeyboardButton("✅ تأیید و ذخیره", callback_data="final_confirm")],
            [InlineKeyboardButton("✏️ ویرایش دارو", callback_data="change_drug")],
            [InlineKeyboardButton("📅 ویرایش تاریخ", callback_data="back_to_date_entry")],
            [InlineKeyboardButton("🔢 ویرایش تعداد", callback_data="back_to_quantity_entry")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"جزئیات دارو:\n\n"
            f"نام: {drug_name}\n"
            f"قیمت: {drug_price}\n"
            f"تاریخ انقضا: {expiry_date}\n"
            f"تعداد: {quantity}\n\n"
            "آیا اطلاعات وارد شده صحیح است؟",
            reply_markup=reply_markup
        )
        return States.CONFIRM_ADD_DRUG
        
    except Exception as e:
        logger.error(f"Error in confirm_add_drug: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return States.ENTER_QUANTITY

async def save_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save drug item to database"""
    try:
        query = update.callback_query
        await query.answer()
        
        drug_name, drug_price = context.user_data['selected_drug']
        expiry_date = context.user_data['expiry_date']
        quantity = context.user_data['quantity']
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                INSERT INTO drug_items (
                    user_id, name, price, date, quantity
                ) VALUES (%s, %s, %s, %s, %s)
                ''', (
                    update.effective_user.id,
                    drug_name,
                    drug_price,
                    expiry_date,
                    quantity
                ))
                conn.commit()
                
                await query.edit_message_text(
                    "✅ دارو با موفقیت به لیست شما اضافه شد!",
                    reply_markup=None
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
                    text="به منوی اصلی بازگشتید. لطفا یک گزینه را انتخاب کنید:",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error saving drug: {e}")
            await query.edit_message_text("خطا در ذخیره دارو. لطفا دوباره تلاش کنید.")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
            
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in save_drug_item: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return States.CONFIRM_ADD_DRUG

async def list_my_drugs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all drugs added by the user"""
    try:
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT id, name, price, date, quantity 
                FROM drug_items 
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 100
                ''', (update.effective_user.id,))
                drugs = cursor.fetchall()
                
                if not drugs:
                    await update.message.reply_text("هنوز هیچ دارویی اضافه نکرده‌اید.")
                    return
                
                message = "لیست داروهای شما:\n\n"
                for i, drug in enumerate(drugs, start=1):
                    message += (
                        f"{i}. {drug['name']}\n"
                        f"   قیمت: {drug['price']}\n"
                        f"   تاریخ انقضا: {drug['date']}\n"
                        f"   تعداد: {drug['quantity']}\n\n"
                    )
                
                # Add pagination if needed
                keyboard = [
                    [InlineKeyboardButton("✏️ ویرایش داروها", callback_data="edit_drugs")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    message,
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error listing drugs: {e}")
            await update.message.reply_text("خطا در دریافت لیست داروها.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in list_my_drugs: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")

async def edit_drugs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show interface for editing drugs"""
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
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 50
                ''', (update.effective_user.id,))
                drugs = cursor.fetchall()
                
                if not drugs:
                    await query.edit_message_text("هنوز هیچ دارویی برای ویرایش وجود ندارد.")
                    return
                
                keyboard = []
                for drug in drugs:
                    btn_text = format_button_text(f"{drug['name']} ({drug['quantity']})")
                    keyboard.append([InlineKeyboardButton(
                        btn_text,
                        callback_data=f"edit_drug_{drug['id']}"
                    )])
                
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_list")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    "لطفا دارویی که می‌خواهید ویرایش کنید را انتخاب کنید:",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error in edit_drugs: {e}")
            await query.edit_message_text("خطا در دریافت لیست داروها.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in edit_drugs: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")

async def edit_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show drug item for editing"""
    try:
        query = update.callback_query
        await query.answer()
        
        if not query.data.startswith("edit_drug_"):
            return
        
        drug_id = int(query.data.split("_")[2])
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
                    [InlineKeyboardButton("📅 ویرایش تاریخ انقضا", callback_data="edit_date")],
                    [InlineKeyboardButton("🔢 ویرایش تعداد", callback_data="edit_quantity")],
                    [InlineKeyboardButton("🗑️ حذف دارو", callback_data="delete_drug")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_list")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"ویرایش دارو:\n\n"
                    f"نام: {drug['name']}\n"
                    f"قیمت: {drug['price']}\n"
                    f"تاریخ انقضا: {drug['date']}\n"
                    f"تعداد: {drug['quantity']}\n\n"
                    "لطفا عملیات مورد نظر را انتخاب کنید:",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error in edit_drug_item: {e}")
            await query.edit_message_text("خطا در دریافت اطلاعات دارو.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in edit_drug_item: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")

async def handle_drug_edit_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drug edit actions (date, quantity, delete)"""
    try:
        query = update.callback_query
        await query.answer()
        
        action = query.data
        drug_id = context.user_data.get('edit_drug_id')
        
        if not drug_id:
            await query.edit_message_text("خطا در شناسایی دارو.")
            return
        
        if action == "edit_date":
            await query.edit_message_text(
                "لطفا تاریخ انقضای جدید را وارد کنید (فرمت: YYYY/MM/DD):",
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
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "آیا مطمئن هستید که می‌خواهید این دارو را حذف کنید؟",
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logger.error(f"Error in handle_drug_edit_action: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")

async def update_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Update drug item in database"""
    try:
        drug_id = context.user_data.get('edit_drug_id')
        action = context.user_data.get('edit_action')
        new_value = update.message.text.strip()
        
        if not drug_id or not action:
            await update.message.reply_text("خطا در پردازش درخواست.")
            return ConversationHandler.END
            
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                if action == "edit_date":
                    if not validate_date(new_value):
                        await update.message.reply_text("فرمت تاریخ نامعتبر است. لطفا به فرمت YYYY/MM/DD وارد کنید.")
                        return States.EDIT_ITEM
                    
                    cursor.execute('''
                    UPDATE drug_items 
                    SET date = %s 
                    WHERE id = %s AND user_id = %s
                    ''', (new_value, drug_id, update.effective_user.id))
                    
                elif action == "edit_quantity":
                    try:
                        quantity = int(new_value)
                        if quantity <= 0:
                            raise ValueError
                    except ValueError:
                        await update.message.reply_text("لطفا یک عدد صحیح مثبت وارد کنید.")
                        return States.EDIT_ITEM
                    
                    cursor.execute('''
                    UPDATE drug_items 
                    SET quantity = %s 
                    WHERE id = %s AND user_id = %s
                    ''', (quantity, drug_id, update.effective_user.id))
                
                conn.commit()
                
                await update.message.reply_text("✅ تغییرات با موفقیت ذخیره شد.")
                
                # Return to drug edit menu
                context.user_data['edit_drug_id'] = drug_id
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
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def handle_drug_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drug deletion confirmation"""
    try:
        query = update.callback_query
        await query.answer()
        
        drug_id = context.user_data.get('edit_drug_id')
        
        if not drug_id:
            await query.edit_message_text("خطا در شناسایی دارو.")
            return
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                DELETE FROM drug_items 
                WHERE id = %s AND user_id = %s
                ''', (drug_id, update.effective_user.id))
                conn.commit()
                
                await query.edit_message_text(
                    "✅ دارو با موفقیت حذف شد.",
                    reply_markup=None
                )
                
                # Return to drugs list
                return await edit_drugs(update, context)
                
        except Exception as e:
            logger.error(f"Error deleting drug: {e}")
            await query.edit_message_text("خطا در حذف دارو.")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in handle_drug_deletion: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")

# Needs Management Handlers
async def add_need_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start adding a new need"""
    try:
        await update.message.reply_text(
            "لطفا نام داروی مورد نیاز را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.ADD_NEED_NAME
    except Exception as e:
        logger.error(f"Error in add_need_start: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def add_need_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get description for the need"""
    try:
        need_name = update.message.text.strip()
        if len(need_name) < 2:
            await update.message.reply_text("لطفا نام معتبری وارد کنید (حداقل 2 حرف).")
            return States.ADD_NEED_NAME
            
        context.user_data['need_name'] = need_name
        
        await update.message.reply_text(
            "لطفا توضیحاتی درباره این نیاز وارد کنید (اختیاری):",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.ADD_NEED_DESC
    except Exception as e:
        logger.error(f"Error in add_need_description: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def add_need_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get quantity for the need"""
    try:
        need_desc = update.message.text.strip()
        context.user_data['need_desc'] = need_desc if need_desc else "بدون توضیح"
        
        await update.message.reply_text(
            "لطفا تعداد مورد نیاز را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.ADD_NEED_QUANTITY
    except Exception as e:
        logger.error(f"Error in add_need_quantity: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def save_need(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save the need to database"""
    try:
        quantity = update.message.text.strip()
        
        try:
            quantity = int(quantity)
            if quantity <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("لطفا یک عدد صحیح مثبت وارد کنید.")
            return States.ADD_NEED_QUANTITY
        
        need_name = context.user_data.get('need_name')
        need_desc = context.user_data.get('need_desc')
        
        if not need_name:
            await update.message.reply_text("خطا در پردازش اطلاعات. لطفا دوباره شروع کنید.")
            return ConversationHandler.END
            
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                INSERT INTO user_needs (
                    user_id, name, description, quantity
                ) VALUES (%s, %s, %s, %s)
                ''', (
                    update.effective_user.id,
                    need_name,
                    need_desc,
                    quantity
                ))
                conn.commit()
                
                await update.message.reply_text(
                    "✅ نیاز شما با موفقیت ثبت شد!",
                    reply_markup=ReplyKeyboardRemove()
                )
                
                # Check for matches immediately
                await check_for_matches(update.effective_user.id, context)
                
                # Return to main menu
                keyboard = [
                    ['اضافه کردن دارو', 'جستجوی دارو'],
                    ['لیست داروهای من', 'ثبت نیاز جدید'],
                    ['لیست نیازهای من']
                ]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="به منوی اصلی بازگشتید. لطفا یک گزینه را انتخاب کنید:",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error saving need: {e}")
            await update.message.reply_text("خطا در ثبت نیاز. لطفا دوباره تلاش کنید.")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
            
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in save_need: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def list_my_needs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all needs added by the user"""
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
                LIMIT 100
                ''', (update.effective_user.id,))
                needs = cursor.fetchall()
                
                if not needs:
                    await update.message.reply_text("هنوز هیچ نیازی ثبت نکرده‌اید.")
                    return
                
                message = "لیست نیازهای شما:\n\n"
                for i, need in enumerate(needs, start=1):
                    message += (
                        f"{i}. {need['name']}\n"
                        f"   توضیحات: {need['description']}\n"
                        f"   تعداد: {need['quantity']}\n\n"
                    )
                
                # Add edit button
                keyboard = [
                    [InlineKeyboardButton("✏️ ویرایش نیازها", callback_data="edit_needs")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    message,
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error listing needs: {e}")
            await update.message.reply_text("خطا در دریافت لیست نیازها.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in list_my_needs: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")

async def edit_needs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show interface for editing needs"""
    try:
        query = update.callback_query
        await query.answer()
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT id, name, quantity 
                FROM user_needs 
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 50
                ''', (update.effective_user.id,))
                needs = cursor.fetchall()
                
                if not needs:
                    await query.edit_message_text("هنوز هیچ نیازی برای ویرایش وجود ندارد.")
                    return
                
                keyboard = []
                for need in needs:
                    btn_text = format_button_text(f"{need['name']} ({need['quantity']})")
                    keyboard.append([InlineKeyboardButton(
                        btn_text,
                        callback_data=f"edit_need_{need['id']}"
                    )])
                
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_needs_list")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    "لطفا نیازی که می‌خواهید ویرایش کنید را انتخاب کنید:",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error in edit_needs: {e}")
            await query.edit_message_text("خطا در دریافت لیست نیازها.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in edit_needs: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")

async def edit_need_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show need item for editing"""
    try:
        query = update.callback_query
        await query.answer()
        
        if not query.data.startswith("edit_need_"):
            return
        
        need_id = int(query.data.split("_")[2])
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
                    [InlineKeyboardButton("📝 ویرایش توضیحات", callback_data="edit_need_desc")],
                    [InlineKeyboardButton("🔢 ویرایش تعداد", callback_data="edit_need_quantity")],
                    [InlineKeyboardButton("🗑️ حذف نیاز", callback_data="delete_need")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_needs_list")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"ویرایش نیاز:\n\n"
                    f"نام: {need['name']}\n"
                    f"توضیحات: {need['description']}\n"
                    f"تعداد: {need['quantity']}\n\n"
                    "لطفا عملیات مورد نظر را انتخاب کنید:",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error in edit_need_item: {e}")
            await query.edit_message_text("خطا در دریافت اطلاعات نیاز.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in edit_need_item: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")

async def handle_need_edit_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle need edit actions (name, desc, quantity, delete)"""
    try:
        query = update.callback_query
        await query.answer()
        
        action = query.data
        need_id = context.user_data.get('edit_need_id')
        
        if not need_id:
            await query.edit_message_text("خطا در شناسایی نیاز.")
            return
        
        if action == "edit_need_name":
            await query.edit_message_text(
                "لطفا نام جدید را وارد کنید:",
                reply_markup=None
            )
            context.user_data['edit_action'] = "edit_name"
            return States.EDIT_NEED
        elif action == "edit_need_desc":
            await query.edit_message_text(
                "لطفا توضیحات جدید را وارد کنید:",
                reply_markup=None
            )
            context.user_data['edit_action'] = "edit_desc"
            return States.EDIT_NEED
        elif action == "edit_need_quantity":
            await query.edit_message_text(
                "لطفا تعداد جدید را وارد کنید:",
                reply_markup=None
            )
            context.user_data['edit_action'] = "edit_quantity"
            return States.EDIT_NEED
        elif action == "delete_need":
            keyboard = [
                [InlineKeyboardButton("✅ بله، حذف کن", callback_data="confirm_need_delete")],
                [InlineKeyboardButton("❌ انصراف", callback_data="cancel_need_delete")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "آیا مطمئن هستید که می‌خواهید این نیاز را حذف کنید؟",
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logger.error(f"Error in handle_need_edit_action: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")

async def update_need_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Update need item in database"""
    try:
        need_id = context.user_data.get('edit_need_id')
        action = context.user_data.get('edit_action')
        new_value = update.message.text.strip()
        
        if not need_id or not action:
            await update.message.reply_text("خطا در پردازش درخواست.")
            return ConversationHandler.END
            
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                if action == "edit_name":
                    if len(new_value) < 2:
                        await update.message.reply_text("لطفا نام معتبری وارد کنید (حداقل 2 حرف).")
                        return States.EDIT_NEED
                    
                    cursor.execute('''
                    UPDATE user_needs 
                    SET name = %s 
                    WHERE id = %s AND user_id = %s
                    ''', (new_value, need_id, update.effective_user.id))
                    
                elif action == "edit_desc":
                    cursor.execute('''
                    UPDATE user_needs 
                    SET description = %s 
                    WHERE id = %s AND user_id = %s
                    ''', (new_value, need_id, update.effective_user.id))
                    
                elif action == "edit_quantity":
                    try:
                        quantity = int(new_value)
                        if quantity <= 0:
                            raise ValueError
                    except ValueError:
                        await update.message.reply_text("لطفا یک عدد صحیح مثبت وارد کنید.")
                        return States.EDIT_NEED
                    
                    cursor.execute('''
                    UPDATE user_needs 
                    SET quantity = %s 
                    WHERE id = %s AND user_id = %s
                    ''', (quantity, need_id, update.effective_user.id))
                
                conn.commit()
                
                await update.message.reply_text("✅ تغییرات با موفقیت ذخیره شد.")
                
                # Return to need edit menu
                context.user_data['edit_need_id'] = need_id
                return await edit_need_item(update, context)
                
        except Exception as e:
            logger.error(f"Error updating need: {e}")
            await update.message.reply_text("خطا در به‌روزرسانی نیاز.")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
            
    except Exception as e:
        logger.error(f"Error in update_need_item: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def handle_need_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle need deletion confirmation"""
    try:
        query = update.callback_query
        await query.answer()
        
        need_id = context.user_data.get('edit_need_id')
        
        if not need_id:
            await query.edit_message_text("خطا در شناسایی نیاز.")
            return
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                DELETE FROM user_needs 
                WHERE id = %s AND user_id = %s
                ''', (need_id, update.effective_user.id))
                conn.commit()
                
                await query.edit_message_text(
                    "✅ نیاز با موفقیت حذف شد.",
                    reply_markup=None
                )
                
                # Return to needs list
                return await edit_needs(update, context)
                
        except Exception as e:
            logger.error(f"Error deleting need: {e}")
            await query.edit_message_text("خطا در حذف نیاز.")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in handle_need_deletion: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")

# Trading Handlers
async def search_drug_for_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start drug search process for trading"""
    try:
        await update.message.reply_text(
            "لطفا نام دارو را برای جستجو و تبادل وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.SEARCH_DRUG_FOR_ADDING
    except Exception as e:
        logger.error(f"Error in search_drug_for_trading: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def handle_trading_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drug search for trading and show results"""
    try:
        search_query = update.message.text.strip()
        if not search_query or len(search_query) < 2:
            await update.message.reply_text("لطفا حداقل 2 حرف برای جستجو وارد کنید.")
            return States.SEARCH_DRUG_FOR_ADDING
        
        # Search in drug list
        results = []
        for name, price in drug_list:
            if search_query.lower() in name.lower():
                results.append((name, price))
        
        if not results:
            await update.message.reply_text(
                "هیچ نتیجه‌ای یافت نشد. لطفا نام دیگری را امتحان کنید.",
                reply_markup=ReplyKeyboardRemove()
            )
            return States.SEARCH_DRUG_FOR_ADDING
        
        # Limit to top 50 results
        results = results[:50]
        
        # Show results with pagination
        context.user_data['trading_search_results'] = results
        context.user_data['current_trading_page'] = 0
        
        await show_trading_search_results(update, context)
        return States.CONFIRM_DRUG_SELECTION
        
    except Exception as e:
        logger.error(f"Error in handle_trading_search: {e}")
        await update.message.reply_text("خطایی در جستجو رخ داد. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def show_trading_search_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display paginated trading search results"""
    try:
        results = context.user_data.get('trading_search_results', [])
        current_page = context.user_data.get('current_trading_page', 0)
        items_per_page = 10
        total_pages = (len(results) + items_per_page - 1) // items_per_page
        
        if not results:
            await update.message.reply_text("هیچ نتیجه‌ای برای نمایش وجود ندارد.")
            return States.SEARCH_DRUG_FOR_ADDING
        
        start_idx = current_page * items_per_page
        end_idx = min(start_idx + items_per_page, len(results))
        page_results = results[start_idx:end_idx]
        
        message = "نتایج جستجو برای تبادل:\n\n"
        for i, (name, price) in enumerate(page_results, start=1):
            message += f"{start_idx + i}. {name} - {price}\n"
        
        # Add pagination controls
        keyboard = []
        row = []
        
        # Add drug selection buttons (2 per row)
        for i, (name, price) in enumerate(page_results, start=1):
            btn_text = format_button_text(f"{start_idx + i}. {name}")
            row.append(InlineKeyboardButton(
                btn_text,
                callback_data=f"select_drug_{start_idx + i - 1}"
            ))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        
        if row:
            keyboard.append(row)
        
        # Add pagination navigation
        nav_buttons = []
        if current_page > 0:
            nav_buttons.append(InlineKeyboardButton("⏪ قبلی", callback_data="prev_trading_page"))
        
        nav_buttons.append(InlineKeyboardButton(
            f"صفحه {current_page + 1}/{total_pages}",
            callback_data="current_trading_page"
        ))
        
        if current_page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("بعدی ⏩", callback_data="next_trading_page"))
        
        keyboard.append(nav_buttons)
        
        # Add back button
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_trading_search")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text=message,
                    reply_markup=reply_markup
                )
            except:
                await update.callback_query.message.reply_text(
                    text=message,
                    reply_markup=reply_markup
                )
        else:
            await update.message.reply_text(
                text=message,
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logger.error(f"Error showing trading search results: {e}")
        await update.message.reply_text("خطایی در نمایش نتایج رخ داد.")

async def handle_trading_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pagination for trading search results"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "next_trading_page":
        context.user_data['current_trading_page'] += 1
    elif query.data == "prev_trading_page":
        context.user_data['current_trading_page'] -= 1
    
    await show_trading_search_results(update, context)
    return States.CONFIRM_DRUG_SELECTION

async def select_pharmacy_for_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Select a pharmacy to trade with"""
    try:
        query = update.callback_query
        await query.answer()
        
        if not query.data.startswith("select_drug_"):
            return
        
        drug_idx = int(query.data.split("_")[2])
        results = context.user_data.get('trading_search_results', [])
        
        if drug_idx < 0 or drug_idx >= len(results):
            await query.edit_message_text("خطا در انتخاب دارو. لطفا دوباره تلاش کنید.")
            return States.SEARCH_DRUG_FOR_ADDING
        
        drug_name, drug_price = results[drug_idx]
        context.user_data['trading_drug'] = (drug_name, drug_price)
        
        # Find pharmacies that have this drug
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT di.id, di.quantity, di.price, di.date,
                       u.id as user_id, p.name as pharmacy_name
                FROM drug_items di
                JOIN users u ON di.user_id = u.id
                JOIN pharmacies p ON u.id = p.user_id
                WHERE di.name = %s AND di.user_id != %s AND di.quantity > 0
                ORDER BY di.created_at DESC
                LIMIT 50
                ''', (drug_name, update.effective_user.id))
                pharmacies = cursor.fetchall()
                
                if not pharmacies:
                    await query.edit_message_text(
                        f"هیچ داروخانه‌ای با داروی {drug_name} یافت نشد.",
                        reply_markup=None
                    )
                    return States.SEARCH_DRUG_FOR_ADDING
                
                # Prepare keyboard with pharmacy options
                keyboard = []
                for pharma in pharmacies:
                    btn_text = format_button_text(
                        f"{pharma['pharmacy_name']} - {pharma['quantity']} عدد"
                    )
                    keyboard.append([InlineKeyboardButton(
                        btn_text,
                        callback_data=f"pharmacy_{pharma['id']}"
                    )])
                
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_drug_selection")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"داروخانه‌های دارای {drug_name}:\n\n"
                    "لطفا داروخانه مورد نظر را انتخاب کنید:",
                    reply_markup=reply_markup
                )
                return States.SELECT_PHARMACY
                
        except Exception as e:
            logger.error(f"Error finding pharmacies: {e}")
            await query.edit_message_text("خطا در یافتن داروخانه‌ها.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in select_pharmacy_for_trading: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return States.SEARCH_DRUG_FOR_ADDING

async def select_pharmacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pharmacy selection for trading"""
    try:
        query = update.callback_query
        await query.answer()
        
        if not query.data.startswith("pharmacy_"):
            return
        
        drug_item_id = int(query.data.split("_")[1])
        context.user_data['selected_drug_item'] = drug_item_id
        
        # Get drug details
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT di.name, di.price, di.quantity, di.date,
                       p.name as pharmacy_name, p.user_id as pharmacy_user_id
                FROM drug_items di
                JOIN pharmacies p ON di.user_id = p.user_id
                WHERE di.id = %s
                ''', (drug_item_id,))
                drug = cursor.fetchone()
                
                if not drug:
                    await query.edit_message_text("اطلاعات دارو یافت نشد.")
                    return States.SELECT_PHARMACY
                
                context.user_data['pharmacy_id'] = drug['pharmacy_user_id']
                
                await query.edit_message_text(
                    f"جزئیات دارو از داروخانه {drug['pharmacy_name']}:\n\n"
                    f"نام: {drug['name']}\n"
                    f"قیمت: {drug['price']}\n"
                    f"تاریخ انقضا: {drug['date']}\n"
                    f"موجودی: {drug['quantity']}\n\n"
                    "لطفا تعداد مورد نیاز برای تبادل را وارد کنید:",
                    reply_markup=None
                )
                return States.SELECT_QUANTITY
                
        except Exception as e:
            logger.error(f"Error getting drug details: {e}")
            await query.edit_message_text("خطا در دریافت اطلاعات دارو.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in select_pharmacy: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return States.SELECT_PHARMACY

async def confirm_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm offer details before sending"""
    try:
        quantity = update.message.text.strip()
        
        try:
            quantity = int(quantity)
            if quantity <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("لطفا یک عدد صحیح مثبت وارد کنید.")
            return States.SELECT_QUANTITY
        
        drug_item_id = context.user_data.get('selected_drug_item')
        pharmacy_id = context.user_data.get('pharmacy_id')
        
        if not drug_item_id or not pharmacy_id:
            await update.message.reply_text("خطا در پردازش اطلاعات. لطفا دوباره شروع کنید.")
            return ConversationHandler.END
            
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                # Get drug details
                cursor.execute('''
                SELECT di.name, di.price, p.name as pharmacy_name
                FROM drug_items di
                JOIN pharmacies p ON di.user_id = p.user_id
                WHERE di.id = %s
                ''', (drug_item_id,))
                drug = cursor.fetchone()
                
                if not drug:
                    await update.message.reply_text("اطلاعات دارو یافت نشد.")
                    return ConversationHandler.END
                
                # Calculate total price
                price_value = parse_price(drug['price'])
                total_price = price_value * quantity
                formatted_total = format_price(total_price)
                
                context.user_data['offer_details'] = {
                    'drug_name': drug['name'],
                    'drug_price': drug['price'],
                    'pharmacy_name': drug['pharmacy_name'],
                    'quantity': quantity,
                    'total_price': total_price
                }
                
                keyboard = [
                    [InlineKeyboardButton("✅ تأیید و ارسال پیشنهاد", callback_data="send_offer")],
                    [InlineKeyboardButton("✏️ ویرایش تعداد", callback_data="back_to_quantity")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_pharmacies")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    f"جزئیات پیشنهاد تبادل:\n\n"
                    f"دارو: {drug['name']}\n"
                    f"داروخانه: {drug['pharmacy_name']}\n"
                    f"قیمت واحد: {drug['price']}\n"
                    f"تعداد: {quantity}\n"
                    f"قیمت کل: {formatted_total}\n\n"
                    "آیا مایل به ارسال این پیشنهاد هستید؟",
                    reply_markup=reply_markup
                )
                return States.CONFIRM_OFFER
                
        except Exception as e:
            logger.error(f"Error confirming offer: {e}")
            await update.message.reply_text("خطا در محاسبه پیشنهاد.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in confirm_offer: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def send_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the trade offer to the pharmacy"""
    try:
        query = update.callback_query
        await query.answer()
        
        offer_details = context.user_data.get('offer_details')
        drug_item_id = context.user_data.get('selected_drug_item')
        pharmacy_id = context.user_data.get('pharmacy_id')
        
        if not offer_details or not drug_item_id or not pharmacy_id:
            await query.edit_message_text("خطا در پردازش اطلاعات. لطفا دوباره شروع کنید.")
            return ConversationHandler.END
            
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Create offer record
                cursor.execute('''
                INSERT INTO offers (
                    pharmacy_id, buyer_id, total_price, status
                ) VALUES (%s, %s, %s, 'pending')
                RETURNING id
                ''', (
                    pharmacy_id,
                    update.effective_user.id,
                    offer_details['total_price']
                ))
                offer_id = cursor.fetchone()[0]
                
                # Add offer item
                cursor.execute('''
                INSERT INTO offer_items (
                    offer_id, drug_name, price, quantity
                ) VALUES (%s, %s, %s, %s)
                ''', (
                    offer_id,
                    offer_details['drug_name'],
                    offer_details['drug_price'],
                    offer_details['quantity']
                ))
                
                conn.commit()
                
                # Notify pharmacy
                try:
                    buyer_name = update.effective_user.full_name
                    formatted_total = format_price(offer_details['total_price'])
                    
                    keyboard = [
                        [
                            InlineKeyboardButton("✅ قبول", callback_data=f"offer_accept_{offer_id}"),
                            InlineKeyboardButton("❌ رد", callback_data=f"offer_reject_{offer_id}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await context.bot.send_message(
                        chat_id=pharmacy_id,
                        text=f"📩 پیشنهاد تبادل جدید:\n\n"
                             f"از: {buyer_name}\n"
                             f"دارو: {offer_details['drug_name']}\n"
                             f"تعداد: {offer_details['quantity']}\n"
                             f"قیمت واحد: {offer_details['drug_price']}\n"
                             f"قیمت کل: {formatted_total}\n\n"
                             "لطفا این پیشنهاد را بررسی کنید:",
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    logger.error(f"Failed to notify pharmacy: {e}")
                
                await query.edit_message_text(
                    "✅ پیشنهاد شما با موفقیت ارسال شد!\n\n"
                    "پس از بررسی توسط داروخانه، نتیجه به شما اطلاع داده خواهد شد.",
                    reply_markup=None
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
                    text="به منوی اصلی بازگشتید. لطفا یک گزینه را انتخاب کنید:",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error sending offer: {e}")
            await query.edit_message_text("خطا در ارسال پیشنهاد.")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
            
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in send_offer: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return States.CONFIRM_OFFER

async def handle_offer_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pharmacy's response to an offer"""
    try:
        query = update.callback_query
        await query.answer()
        
        if not query.data.startswith("offer_"):
            return
        
        action = query.data.split("_")[1]
        offer_id = int(query.data.split("_")[2])
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                # Get offer details
                cursor.execute('''
                SELECT o.id, o.buyer_id, o.total_price,
                       oi.drug_name, oi.quantity, oi.price,
                       u.first_name, u.last_name
                FROM offers o
                JOIN offer_items oi ON o.id = oi.offer_id
                JOIN users u ON o.buyer_id = u.id
                WHERE o.id = %s AND o.pharmacy_id = %s
                ''', (offer_id, update.effective_user.id))
                offer = cursor.fetchone()
                
                if not offer:
                    await query.edit_message_text("پیشنهاد یافت نشد.")
                    return
                
                # Update offer status
                if action == "accept":
                    new_status = "accepted"
                    response_text = "پذیرفته شد"
                else:
                    new_status = "rejected"
                    response_text = "رد شد"
                
                cursor.execute('''
                UPDATE offers 
                SET status = %s 
                WHERE id = %s
                ''', (new_status, offer_id))
                
                # If accepted, reduce drug quantity
                if action == "accept":
                    cursor.execute('''
                    UPDATE drug_items 
                    SET quantity = quantity - %s 
                    WHERE user_id = %s AND name = %s AND quantity >= %s
                    RETURNING id
                    ''', (
                        offer['quantity'],
                        update.effective_user.id,
                        offer['drug_name'],
                        offer['quantity']
                    ))
                    
                    if not cursor.fetchone():
                        await query.edit_message_text(
                            "❌ موجودی کافی نیست. لطفا موجودی دارو را بررسی کنید.",
                            reply_markup=None
                        )
                        conn.rollback()
                        return
                
                conn.commit()
                
                # Notify buyer
                try:
                    formatted_total = format_price(offer['total_price'])
                    
                    if action == "accept":
                        buyer_message = (
                            f"✅ پیشنهاد شما پذیرفته شد!\n\n"
                            f"دارو: {offer['drug_name']}\n"
                            f"تعداد: {offer['quantity']}\n"
                            f"قیمت کل: {formatted_total}\n\n"
                            f"لطفا برای تکمیل تبادل با داروخانه تماس بگیرید."
                        )
                    else:
                        buyer_message = (
                            f"❌ پیشنهاد شما رد شد.\n\n"
                            f"دارو: {offer['drug_name']}\n"
                            f"تعداد: {offer['quantity']}\n"
                            f"قیمت کل: {formatted_total}"
                        )
                    
                    await context.bot.send_message(
                        chat_id=offer['buyer_id'],
                        text=buyer_message
                    )
                except Exception as e:
                    logger.error(f"Failed to notify buyer: {e}")
                
                await query.edit_message_text(
                    f"پیشنهاد با موفقیت {response_text}.",
                    reply_markup=None
                )
                
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
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")

async def handle_match_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user clicking on a match notification"""
    try:
        query = update.callback_query
        await query.answer()
        
        if not query.data.startswith("view_match_"):
            return
        
        parts = query.data.split("_")
        drug_id = int(parts[2])
        need_id = int(parts[3])
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                # Get drug details
                cursor.execute('''
                SELECT di.name, di.price, di.quantity, di.date,
                       p.name as pharmacy_name, p.user_id as pharmacy_id
                FROM drug_items di
                JOIN pharmacies p ON di.user_id = p.user_id
                WHERE di.id = %s
                ''', (drug_id,))
                drug = cursor.fetchone()
                
                # Get need details
                cursor.execute('''
                SELECT name, quantity 
                FROM user_needs 
                WHERE id = %s AND user_id = %s
                ''', (need_id, update.effective_user.id))
                need = cursor.fetchone()
                
                if not drug or not need:
                    await query.edit_message_text("اطلاعات یافت نشد.")
                    return
                
                context.user_data['match_details'] = {
                    'drug_id': drug_id,
                    'pharmacy_id': drug['pharmacy_id'],
                    'drug_name': drug['name'],
                    'drug_price': drug['price'],
                    'drug_quantity': drug['quantity'],
                    'pharmacy_name': drug['pharmacy_name'],
                    'need_id': need_id,
                    'need_name': need['name'],
                    'need_quantity': need['quantity']
                }
                
                keyboard = [
                    [InlineKeyboardButton("📩 ارسال پیشنهاد تبادل", callback_data="create_offer_from_match")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"جزئیات تطابق:\n\n"
                    f"نیاز شما: {need['name']} (تعداد: {need['quantity']})\n"
                    f"داروی موجود: {drug['name']}\n"
                    f"داروخانه: {drug['pharmacy_name']}\n"
                    f"قیمت: {drug['price']}\n"
                    f"موجودی: {drug['quantity']}\n"
                    f"تاریخ انقضا: {drug['date']}\n\n"
                    "آیا مایل به ارسال پیشنهاد تبادل هستید؟",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error handling match notification: {e}")
            await query.edit_message_text("خطا در دریافت اطلاعات تطابق.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in handle_match_notification: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")

async def create_offer_from_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create offer from match notification"""
    try:
        query = update.callback_query
        await query.answer()
        
        match_details = context.user_data.get('match_details')
        if not match_details:
            await query.edit_message_text("اطلاعات تطابق یافت نشد.")
            return ConversationHandler.END
            
        # Use the minimum of available quantity and needed quantity
        quantity = min(match_details['drug_quantity'], match_details['need_quantity'])
        
        # Calculate total price
        price_value = parse_price(match_details['drug_price'])
        total_price = price_value * quantity
        formatted_total = format_price(total_price)
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Create offer record
                cursor.execute('''
                INSERT INTO offers (
                    pharmacy_id, buyer_id, total_price, status
                ) VALUES (%s, %s, %s, 'pending')
                RETURNING id
                ''', (
                    match_details['pharmacy_id'],
                    update.effective_user.id,
                    total_price
                ))
                offer_id = cursor.fetchone()[0]
                
                # Add offer item
                cursor.execute('''
                INSERT INTO offer_items (
                    offer_id, drug_name, price, quantity
                ) VALUES (%s, %s, %s, %s)
                ''', (
                    offer_id,
                    match_details['drug_name'],
                    match_details['drug_price'],
                    quantity
                ))
                
                conn.commit()
                
                # Notify pharmacy
                try:
                    buyer_name = update.effective_user.full_name
                    
                    keyboard = [
                        [
                            InlineKeyboardButton("✅ قبول", callback_data=f"offer_accept_{offer_id}"),
                            InlineKeyboardButton("❌ رد", callback_data=f"offer_reject_{offer_id}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await context.bot.send_message(
                        chat_id=match_details['pharmacy_id'],
                        text=f"📩 پیشنهاد تبادل جدید:\n\n"
                             f"از: {buyer_name}\n"
                             f"دارو: {match_details['drug_name']}\n"
                             f"تعداد: {quantity}\n"
                             f"قیمت واحد: {match_details['drug_price']}\n"
                             f"قیمت کل: {formatted_total}\n\n"
                             "لطفا این پیشنهاد را بررسی کنید:",
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    logger.error(f"Failed to notify pharmacy: {e}")
                
                await query.edit_message_text(
                    "✅ پیشنهاد شما با موفقیت ارسال شد!\n\n"
                    "پس از بررسی توسط داروخانه، نتیجه به شما اطلاع داده خواهد شد.",
                    reply_markup=None
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
                    text="به منوی اصلی بازگشتید. لطفا یک گزینه را انتخاب کنید:",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error creating offer from match: {e}")
            await query.edit_message_text("خطا در ارسال پیشنهاد.")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
            
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in create_offer_from_match: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

# Error Handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors and handle them gracefully"""
    try:
        logger.error(f"Update {update} caused error {context.error}")
        
        # Log the full traceback
        tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
        tb_string = ''.join(tb_list)
        logger.error(f"Traceback:\n{tb_string}")
        
        # Notify admin
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"⚠️ خطا در ربات:\n\n{context.error}\n\n{tb_string[:1000]}..."
            )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")
        
        # Notify user
        if update and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "⚠️ خطایی در پردازش درخواست شما رخ داد. لطفا دوباره تلاش کنید."
                )
            except Exception as e:
                logger.error(f"Failed to notify user: {e}")
    except Exception as e:
        logger.error(f"Error in error_handler: {e}")
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allow the user to cancel the current operation"""
    await update.message.reply_text(
        "عملیات کنسل شد.",
        reply_markup=ReplyKeyboardMarkup([['/start']], resize_keyboard=True)
    )
    return ConversationHandler.END
# Main Function
def main():
    """Start the bot"""
    # Initialize database
    asyncio.run(initialize_db())
    
    # Load drug data
    load_drug_data()
    
    # Create application
    application = ApplicationBuilder() \
        .token("8447101535:AAFMFkqJeMFNBfhzrY1VURkfJI-vu766LrY") \
        .post_init(post_init) \
        .build()
    
    # Add conversation handler for registration
    registration_conv = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(register_pharmacy_name, pattern="^register$"),
            CallbackQueryHandler(admin_verify_start, pattern="^admin_verify$"),
            CallbackQueryHandler(simple_verify_start, pattern="^simple_verify$"),
            CallbackQueryHandler(personnel_login_start, pattern="^personnel_login$")
        ],
        states={
            States.START: [
                CallbackQueryHandler(register_pharmacy_name, pattern="^register$"),
                CallbackQueryHandler(admin_verify_start, pattern="^admin_verify$"),
                CallbackQueryHandler(simple_verify_start, pattern="^simple_verify$"),
                CallbackQueryHandler(personnel_login_start, pattern="^personnel_login$")
            ],
            States.REGISTER_PHARMACY_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_founder_name)
            ],
            States.REGISTER_FOUNDER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_national_card)
            ],
            States.REGISTER_NATIONAL_CARD: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, register_license),
                MessageHandler(filters.ALL & ~filters.COMMAND, register_national_card)
            ],
            States.REGISTER_LICENSE: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, register_medical_card),
                MessageHandler(filters.ALL & ~filters.COMMAND, register_license)
            ],
            States.REGISTER_MEDICAL_CARD: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, register_phone),
                MessageHandler(filters.ALL & ~filters.COMMAND, register_medical_card)
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
            States.SIMPLE_VERIFICATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, simple_verify_code)
            ],
            States.PERSONNEL_LOGIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, verify_personnel_code)
            ]
        },
        fallbacks=[
            CommandHandler('start', start),
            CallbackQueryHandler(handle_back, pattern="^back$"),
            CallbackQueryHandler(cancel, pattern="^cancel$")
        ],
        allow_reentry=True
    )
    
    # Add conversation handler for drug management
    drug_management_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^اضافه کردن دارو$'), search_drug_for_trading),
            MessageHandler(filters.Regex('^جستجوی دارو$'), search_drug)
        ],
        states={
            States.SEARCH_DRUG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_drug_search)
            ],
            States.SELECT_DRUGS: [
                CallbackQueryHandler(handle_search_pagination, pattern="^(next_page|prev_page|current_page)$"),
                CallbackQueryHandler(select_drug_for_adding, pattern="^select_drug_"),
                CallbackQueryHandler(search_drug, pattern="^back_to_search$")
            ],
            States.CONFIRM_DRUG_SELECTION: [
                CallbackQueryHandler(ask_for_expiry_date, pattern="^confirm_drug$"),
                CallbackQueryHandler(search_drug, pattern="^back_to_search$")
            ],
            States.ENTER_EXPIRY_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_for_quantity)
            ],
            States.ENTER_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_add_drug)
            ],
            States.CONFIRM_ADD_DRUG: [
                CallbackQueryHandler(save_drug_item, pattern="^final_confirm$"),
                CallbackQueryHandler(search_drug_for_trading, pattern="^change_drug$"),
                CallbackQueryHandler(ask_for_expiry_date, pattern="^back_to_date_entry$"),
                CallbackQueryHandler(ask_for_quantity, pattern="^back_to_quantity_entry$")
            ],
            States.SEARCH_DRUG_FOR_ADDING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_trading_search)
            ],
            States.SELECT_PHARMACY: [
                CallbackQueryHandler(select_pharmacy, pattern="^pharmacy_"),
                CallbackQueryHandler(select_drug_for_adding, pattern="^back_to_drug_selection$")
            ],
            States.SELECT_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_offer)
            ],
            States.CONFIRM_OFFER: [
                CallbackQueryHandler(send_offer, pattern="^send_offer$"),
                CallbackQueryHandler(select_pharmacy, pattern="^back_to_pharmacies$"),
                CallbackQueryHandler(confirm_offer, pattern="^back_to_quantity$")
            ]
        },
        fallbacks=[
            CommandHandler('start', start),
            CallbackQueryHandler(handle_back, pattern="^back$"),
            CallbackQueryHandler(cancel, pattern="^cancel$")
        ],
        allow_reentry=True
    )
    
    # Add conversation handler for needs management
    needs_management_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^ثبت نیاز جدید$'), add_need_start)
        ],
        states={
            States.ADD_NEED_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_need_description)
            ],
            States.ADD_NEED_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_need_quantity)
            ],
            States.ADD_NEED_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_need)
            ]
        },
        fallbacks=[
            CommandHandler('start', start),
            CallbackQueryHandler(handle_back, pattern="^back$"),
            CallbackQueryHandler(cancel, pattern="^cancel$")
        ],
        allow_reentry=True
    )
    
    # Add conversation handler for editing
    edit_management_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(edit_drugs, pattern="^edit_drugs$"),
            CallbackQueryHandler(edit_needs, pattern="^edit_needs$")
        ],
        states={
            States.EDIT_ITEM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, update_drug_item)
            ],
            States.EDIT_NEED: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, update_need_item)
            ]
        },
        fallbacks=[
            CommandHandler('start', start),
            CallbackQueryHandler(handle_back, pattern="^back$"),
            CallbackQueryHandler(cancel, pattern="^cancel$"),
            CallbackQueryHandler(edit_drugs, pattern="^back_to_list$"),
            CallbackQueryHandler(edit_needs, pattern="^back_to_needs_list$"),
            CallbackQueryHandler(edit_drug_item, pattern="^cancel_delete$"),
            CallbackQueryHandler(edit_need_item, pattern="^cancel_need_delete$"),
            CallbackQueryHandler(handle_drug_deletion, pattern="^confirm_delete$"),
            CallbackQueryHandler(handle_need_deletion, pattern="^confirm_need_delete$")
        ],
        allow_reentry=True
    )
    
    # Add conversation handler for categories setup
    categories_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^تنظیم شاخه‌های دارویی$'), setup_medical_categories)
        ],
        states={
            States.SETUP_CATEGORIES: [
                CallbackQueryHandler(toggle_category, pattern="^togglecat_"),
                CallbackQueryHandler(save_categories, pattern="^save_categories$")
            ]
        },
        fallbacks=[
            CommandHandler('start', start),
            CallbackQueryHandler(handle_back, pattern="^back$")
        ],
        allow_reentry=True
    )
    
    # Add handlers
    application.add_handler(registration_conv)
    application.add_handler(drug_management_conv)
    application.add_handler(needs_management_conv)
    application.add_handler(edit_management_conv)
    application.add_handler(categories_conv)
    
    # Add command handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('generate_code', generate_simple_code))
    application.add_handler(CommandHandler('verify', verify_pharmacy))
    application.add_handler(CommandHandler('upload_excel', upload_excel_start))
    application.add_handler(CommandHandler('generate_personnel_code', generate_personnel_code))
    
    # Add message handlers
    application.add_handler(MessageHandler(filters.Regex('^لیست داروهای من$'), list_my_drugs))
    application.add_handler(MessageHandler(filters.Regex('^لیست نیازهای من$'), list_my_needs))
    
    # Add callback query handler
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Run the bot
    application.run_polling()

async def post_init(application: Application):
    """Post initialization tasks"""
    # Set bot commands
    commands = [
        ("start", "شروع مجدد ربات"),
        ("generate_code", "ساخت کد تایید ساده (ادمین)"),
        ("verify", "تایید داروخانه (ادمین)"),
        ("upload_excel", "آپلود فایل اکسل داروها (ادمین)"),
        ("generate_personnel_code", "ساخت کد پرسنل")
    ]
    
    await application.bot.set_my_commands(commands)

if __name__ == '__main__':
    main()
