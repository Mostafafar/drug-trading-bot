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
    InlineQueryResultArticle,  # Add this
    InputTextMessageContent  # Add this
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
    PERSONNEL_VERIFICATION = auto()  # این خط را اضافه کنید
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
            # ... rest of your initialization code ...
    
            # در بخش initialize_db() این جدول را اضافه کنید:
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS personnel_codes (
                code TEXT PRIMARY KEY,
                creator_id BIGINT REFERENCES pharmacies(user_id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )''')
            logger.info("Verifying tables exist...")
            
            # بررسی جدول users
            cursor.execute("SELECT to_regclass('users')")
            users_table = cursor.fetchone()[0]
            logger.info(f"Users table exists: {users_table}")
            if not users_table:
                raise Exception("Users table creation failed")
            
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
               from_pharmacy BOOLEAN  -- TRUE if from sender, FALSE if from receiver
            )''')

            
            # Simple codes table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS simple_codes (
                code TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_by BIGINT[] DEFAULT array[]::BIGINT[],
                max_uses INTEGER DEFAULT 5
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
        # بقیه هندلرهای موجود...
        # ...

        # Handle different callback patterns
        if query.data == "back":
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
                
    except Exception as e:
        logger.error(f"Error in callback_handler: {e}")
        try:
            if update.callback_query:
                await update.callback_query.answer("خطایی رخ داد. لطفا دوباره تلاش کنید.", show_alert=True)
        except:
            pass

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
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        try:
            await query.edit_message_text(
                "به منوی اصلی بازگشتید. لطفا یک گزینه را انتخاب کنید:",
                reply_markup=None  # Remove any existing inline keyboard
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
    """درخواست ثبت نام با تایید ادمین"""
    try:
        query = update.callback_query
        await query.answer()
        
        # درخواست شماره تلفن از کاربر
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

async def add_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start process to add a drug item with inline query"""
    try:
        await ensure_user(update, context)
        
        # ایجاد دکمه برای جستجوی اینلاین
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
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
async def handle_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline query for drug search"""
    query = update.inline_query.query
    if not query:
        return
    
    results = []
    for idx, (name, price) in enumerate(drug_list):
        if query.lower() in name.lower():
            results.append(
                InlineQueryResultArticle(
                    id=str(idx),
                    title=name,
                    description=price,
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
        if len(results) >= 50:  # محدودیت تعداد نتایج
            break
    
    await update.inline_query.answer(results)

async def handle_chosen_inline_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle selected inline result"""
    result_id = update.chosen_inline_result.result_id
    try:
        idx = int(result_id)
        if 0 <= idx < len(drug_list):
            selected_drug = drug_list[idx]
            context.user_data['selected_drug'] = {
                'name': selected_drug[0],
                'price': selected_drug[1]
            }
            
            await context.bot.send_message(
                chat_id=update.chosen_inline_result.from_user.id,
                text=f"✅ دارو انتخاب شده: {selected_drug[0]}\n💰 قیمت: {selected_drug[1]}\n\n"
                     "📅 لطفا تاریخ انقضا را وارد کنید (مثال: 2026/01/23):"
            )
            return States.ADD_DRUG_DATE
    except Exception as e:
        logger.error(f"Error handling chosen inline result: {e}")
    
    return ConversationHandler.END


async def search_drug_for_adding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for drug to add with comprehensive error handling and logging"""
    try:
        # Get the search term with proper error handling
        try:
            if update.callback_query and update.callback_query.message:
                # Handle case when coming from back button
                await update.callback_query.answer()
                search_term = context.user_data.get('search_term', '')
                message = update.callback_query.message
            elif update.message:
                search_term = update.message.text.strip().lower()
                message = update.message
                context.user_data['search_term'] = search_term
            else:
                logger.error("No message or callback_query in update")
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="خطایی در دریافت پیام رخ داد. لطفا دوباره تلاش کنید."
                )
                return States.SEARCH_DRUG_FOR_ADDING
        except Exception as e:
            logger.error(f"Error getting search term: {e}")
            await update.message.reply_text(
                "خطایی در دریافت نام دارو رخ داد. لطفا دوباره وارد کنید:",
                reply_markup=ReplyKeyboardRemove()
            )
            return States.SEARCH_DRUG_FOR_ADDING

        # Validate search term
        if not search_term or len(search_term) < 2:
            await message.reply_text(
                "حداقل ۲ حرف برای جستجو وارد کنید:",
                reply_markup=ReplyKeyboardRemove()
            )
            return States.SEARCH_DRUG_FOR_ADDING

        # Search in drug list
        matched_drugs = []
        try:
            for name, price in drug_list:
                if name and search_term in name.lower():
                    matched_drugs.append((name, price))
        except Exception as e:
            logger.error(f"Error searching drug list: {e}")
            await message.reply_text(
                "خطایی در جستجوی داروها رخ داد. لطفا دوباره تلاش کنید.",
                reply_markup=ReplyKeyboardRemove()
            )
            return States.SEARCH_DRUG_FOR_ADDING

        # Handle no results case
        if not matched_drugs:
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت به جستجو", callback_data="back_to_search")],
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="back")]
            ]
            
            await message.reply_text(
                "هیچ دارویی با این نام یافت نشد.\n\n"
                "می‌توانید دوباره جستجو کنید یا به منوی اصلی بازگردید.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return States.SEARCH_DRUG_FOR_ADDING

        # Store matched drugs in context
        context.user_data['matched_drugs'] = matched_drugs
        
        # Prepare keyboard with drug options
        # در تابع search_drug_for_adding، قسمت ایجاد keyboard را تغییر دهید:
        keyboard = []
        try:
           for idx, (name, price) in enumerate(matched_drugs[:10]):  # Limit to 10 results
               display_text = f"{format_button_text(name, max_length=25)}\n{format_button_text(price, max_length=25)}"
               keyboard.append([InlineKeyboardButton(display_text, callback_data=f"select_drug_{idx}")])
        except Exception as e:
           logger.error(f"Error preparing keyboard: {e}")
           await message.reply_text(
              "خطایی در آماده‌سازی لیست داروها رخ داد.",
              reply_markup=ReplyKeyboardRemove()
           )
           return States.SEARCH_DRUG_FOR_ADDING


        # Add navigation buttons
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back")])
        keyboard.append([InlineKeyboardButton("❌ لغو", callback_data="cancel")])

        # Prepare message with search results
        message_text = "🔍 نتایج جستجو:\n\n"
        try:
            for idx, (name, price) in enumerate(matched_drugs[:10]):
                message_text += f"{idx+1}. {name} - {price}\n"
            
            if len(matched_drugs) > 10:
                message_text += f"\n➕ {len(matched_drugs)-10} نتیجه دیگر...\n"
            
            message_text += "\nلطفا از لیست بالا انتخاب کنید:"
        except Exception as e:
            logger.error(f"Error preparing message: {e}")
            message_text = "لطفا داروی مورد نظر را انتخاب کنید:"

        # Send the message with keyboard
        try:
            await message.reply_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            return States.SELECT_DRUG_FOR_ADDING
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="خطایی در نمایش نتایج رخ داد. لطفا دوباره تلاش کنید."
            )
            return States.SEARCH_DRUG_FOR_ADDING

    except Exception as e:
        logger.error(f"Unexpected error in search_drug_for_adding: {e}")
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="خطای غیرمنتظره‌ای رخ داد. لطفا دوباره تلاش کنید."
            )
        except:
            pass
        return ConversationHandler.END

async def select_drug_for_adding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Select drug from search results to add"""
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
    """Add expiration date for drug"""
    try:
        if update.callback_query and update.callback_query.data == "back_to_search":
            await update.callback_query.answer()
            return await search_drug_for_adding(update, context)
        
        date = update.message.text
        if not re.match(r'^\d{4}/\d{2}/\d{2}$', date):
            await update.message.reply_text("فرمت تاریخ نامعتبر است. لطفا به صورت 1403/05/15 وارد کنید.")
            return States.ADD_DRUG_DATE
        
        context.user_data['drug_date'] = date
        
        keyboard = [
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_drug_selection")]
        ]
        
        await update.message.reply_text(
            "لطفا تعداد یا مقدار موجود را وارد کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.ADD_DRUG_QUANTITY
    except Exception as e:
        logger.error(f"Error in add_drug_date: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def save_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.callback_query and update.callback_query.data == "back_to_drug_selection":
            await update.callback_query.answer()
            query = update.callback_query
            selected_drug = context.user_data.get('selected_drug', {})
            await query.edit_message_text(
                f"✅ دارو انتخاب شده: {selected_drug.get('name', '')}\n"
                f"💰 قیمت: {selected_drug.get('price', '')}\n\n"
                "📅 لطفا تاریخ انقضا را وارد کنید (مثال: 1403/05/15):"
            )
            return States.ADD_DRUG_DATE

        if not context.user_data.get('selected_drug') or not context.user_data.get('drug_date'):
            logger.error("Missing selected_drug or drug_date in context")
            await update.message.reply_text("اطلاعات دارو ناقص است.")
            return ConversationHandler.END

        try:
            quantity = int(update.message.text)
            if quantity <= 0:
                await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید.")
                return States.ADD_DRUG_QUANTITY

            user = update.effective_user
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor() as cursor:
                    # Log before insertion
                    logger.info(f"Attempting to insert drug: {context.user_data['selected_drug']['name']}")

                    cursor.execute('''
                    INSERT INTO drug_items (user_id, name, price, date, quantity)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    ''', (
                        user.id,
                        context.user_data['selected_drug']['name'],
                        context.user_data['selected_drug']['price'],
                        context.user_data['drug_date'],
                        quantity
                    ))
                    
                    # Get the inserted ID to confirm insertion
                    drug_id = cursor.fetchone()[0]
                    logger.info(f"Drug inserted successfully with ID: {drug_id}")
                    
                    conn.commit()
                    
                    # Verify insertion
                    cursor.execute('SELECT * FROM drug_items WHERE id = %s', (drug_id,))
                    inserted_drug = cursor.fetchone()
                    logger.info(f"Inserted drug record: {inserted_drug}")

                    await update.message.reply_text(
                        f"✅ دارو با موفقیت اضافه شد!\n\n"
                        f"نام: {context.user_data['selected_drug']['name']}\n"
                        f"قیمت: {context.user_data['selected_drug']['price']}\n"
                        f"تاریخ انقضا: {context.user_data['drug_date']}\n"
                        f"تعداد: {quantity}"
                    )

                    # Check for matches
                    context.application.create_task(check_for_matches(user.id, context))

            except psycopg2.Error as e:
                logger.error(f"Database error: {e}")
                if conn:
                    conn.rollback()
                await update.message.reply_text("خطا در ثبت دارو. لطفا دوباره تلاش کنید.")
                return States.ADD_DRUG_QUANTITY
            finally:
                if conn:
                    conn.close()

        except ValueError:
            await update.message.reply_text("لطفا یک عدد صحیح وارد کنید.")
            return States.ADD_DRUG_QUANTITY

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error in save_drug_item: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def list_my_drugs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List user's drug items"""
    conn = None
    try:
        await ensure_user(update, context)
        
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
                    message += (
                        f"• {drug['name']}\n"
                        f"  قیمت: {drug['price']}\n"
                        f"  تاریخ انقضا: {drug['date']}\n"
                        f"  موجودی: {drug['quantity']}\n\n"
                    )
                
                keyboard = [
                    [InlineKeyboardButton(
                        f"✏️ ویرایش داروها\n({len(drugs)} دارو)",
                        callback_data="edit_drugs"
                    )],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
                ]
                
                await update.message.reply_text(
                    message,
                    reply_markup=InlineKeyboardMarkup(keyboard))
                return States.EDIT_DRUG
            else:
                await update.message.reply_text("شما هنوز هیچ دارویی اضافه نکرده‌اید.")
                
    except Exception as e:
        logger.error(f"Error listing drugs: {e}")
        await update.message.reply_text("خطا در دریافت لیست داروها. لطفا دوباره تلاش کنید.")
    finally:
        if conn:
            conn.close()
    
    return ConversationHandler.END

async def edit_drugs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start drug editing process"""
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
    """Start process to add a need"""
    try:
        await ensure_user(update, context)
        await update.message.reply_text("لطفا نام دارویی که نیاز دارید را وارد کنید:")
        return States.ADD_NEED_NAME
    except Exception as e:
        logger.error(f"Error in add_need: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
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
    try:
        context.user_data['need_desc'] = update.message.text
        await update.message.reply_text("لطفا تعداد مورد نیاز را وارد کنید:")
        return States.ADD_NEED_QUANTITY
    except Exception as e:
        logger.error(f"Error in save_need_desc: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def save_need(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save need to database"""
    try:
        try:
            quantity = int(update.message.text)
            if quantity <= 0:
                await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید.")
                return States.ADD_NEED_QUANTITY
            
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
                        context.user_data['need_name'],
                        context.user_data.get('need_desc', ''),
                        quantity
                    ))
                    conn.commit()
                    
                    await update.message.reply_text(
                        f"✅ نیاز شما با موفقیت ثبت شد!\n\n"
                        f"نام: {context.user_data['need_name']}\n"
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
    """List user's needs"""
    try:
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
                        [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
                    ]
                    
                    await update.message.reply_text(
                        message,
                        reply_markup=InlineKeyboardMarkup(keyboard))
                    return States.EDIT_NEED
                else:
                    await update.message.reply_text("شما هنوز هیچ نیازی ثبت نکرده‌اید.")
                    
        except Exception as e:
            logger.error(f"Error listing needs: {e}")
            await update.message.reply_text("خطا در دریافت لیست نیازها. لطفا دوباره تلاش کنید.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in list_my_needs: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def edit_needs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start needs editing process"""
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

# Search and Trade
async def search_drug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start drug search process"""
    try:
        await ensure_user(update, context)
        await update.message.reply_text("لطفا نام دارویی که می‌خواهید جستجو کنید را وارد کنید:")
        return States.SEARCH_DRUG
    except Exception as e:
        logger.error(f"Error in search_drug: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END



async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """جستجوی دارو در داروخانه‌های دیگر"""
    try:
        search_term = update.message.text.strip().lower()
        context.user_data['search_term'] = search_term
        context.user_data['selected_drugs'] = []
        context.user_data['my_drugs'] = []

        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                # جستجو فقط در داروخانه‌های دیگر
                cursor.execute('''
                SELECT 
                    di.id, di.user_id, di.name, di.price, di.date, di.quantity,
                    p.name AS pharmacy_name,
                    similarity(di.name, %s) AS match_score
                FROM drug_items di
                JOIN pharmacies p ON di.user_id = p.user_id
                WHERE 
                    di.quantity > 0 AND
                    di.user_id != %s AND
                    (di.name ILIKE %s OR similarity(di.name, %s) > 0.3)
                ORDER BY match_score DESC, di.price DESC
                LIMIT 20
                ''', (search_term, update.effective_user.id, f'%{search_term}%', search_term))
                
                results = cursor.fetchall()

                if results:
                    # گروه‌بندی نتایج بر اساس داروخانه
                    pharmacies = {}
                    for item in results:
                        pharmacy_id = item['user_id']
                        if pharmacy_id not in pharmacies:
                            pharmacies[pharmacy_id] = {
                                'name': item['pharmacy_name'],
                                'items': []
                            }
                        pharmacies[pharmacy_id]['items'].append(dict(item))
                    
                    context.user_data['pharmacies'] = pharmacies
                    
                    # نمایش نتایج جستجو
                    message = "🔍 نتایج جستجو:\n\n"
                    for pharma_id, pharma_data in pharmacies.items():
                        message += f"🏥 داروخانه: {pharma_data['name']}\n"
                        for item in pharma_data['items']:
                            message += (
                                f"  💊 {item['name']}\n"
                                f"  💰 قیمت: {item['price']}\n"
                                f"  📅 تاریخ انقضا: {item['date']}\n"
                                f"  📦 موجودی: {item['quantity']}\n\n"
                            )
                    
                    keyboard = []
                    for pharmacy_id, pharmacy_data in pharmacies.items():
                        keyboard.append([InlineKeyboardButton(
                            f"🏥 {pharmacy_data['name']} ({len(pharmacy_data['items'])} دارو)", 
                            callback_data=f"pharmacy_{pharmacy_id}"
                        )])
                    
                    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back")])
                    
                    await update.message.reply_text(
                        message,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return States.SELECT_PHARMACY
                else:
                    await update.message.reply_text("هیچ دارویی در داروخانه‌های دیگر یافت نشد.")
                    return ConversationHandler.END
                    
        except Exception as e:
            logger.error(f"خطا در جستجو: {e}")
            await update.message.reply_text("خطا در جستجوی داروها.")
            return States.SEARCH_DRUG
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"خطا در handle_search: {e}")
        await update.message.reply_text("خطایی رخ داد.")
        return ConversationHandler.END

async def select_pharmacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش داروهای دو طرف به صورت کیبرد معمولی با صفحه‌بندی"""
    try:
        query = update.callback_query
        await query.answer()

        # دریافت اطلاعات داروخانه انتخاب شده
        pharmacy_id = int(query.data.split('_')[1])
        user_id = update.effective_user.id
        
        # تنظیم صفحه فعلی اگر وجود ندارد
        if 'current_page' not in context.user_data:
            context.user_data['current_page'] = 0
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                # دریافت اطلاعات داروخانه
                cursor.execute('''
                SELECT p.user_id, p.name as pharmacy_name, u.first_name, u.last_name
                FROM pharmacies p
                JOIN users u ON p.user_id = u.id
                WHERE p.user_id = %s
                ''', (pharmacy_id,))
                pharmacy = cursor.fetchone()
                
                if not pharmacy:
                    await query.edit_message_text("داروخانه یافت نشد.")
                    return States.SEARCH_DRUG
                
                # دریافت داروهای داروخانه هدف
                cursor.execute('''
                SELECT id, name, price, quantity, date 
                FROM drug_items
                WHERE user_id = %s AND quantity > 0
                ORDER BY name
                ''', (pharmacy_id,))
                target_drugs = cursor.fetchall()
                
                # دریافت داروهای کاربر
                cursor.execute('''
                SELECT id, name, price, quantity, date 
                FROM drug_items
                WHERE user_id = %s AND quantity > 0
                ORDER BY name
                ''', (user_id,))
                my_drugs = cursor.fetchall()
                
                # ذخیره در context
                context.user_data.update({
                    'selected_pharmacy': dict(pharmacy),
                    'target_drugs': target_drugs,
                    'my_drugs': my_drugs,
                    'selected_pharmacy_id': pharmacy_id,
                    'selected_items': {
                        'target': [],
                        'mine': []
                    }
                })
                
                # محاسبه تعداد صفحات
                items_per_page = 10
                total_pages = (len(target_drugs) // items_per_page + (1 if len(target_drugs) % items_per_page != 0 else 0))
                
                # ساخت کیبرد معمولی برای داروها با صفحه‌بندی
                keyboard = []
                
                # محاسبه محدوده داروهای صفحه فعلی
                start_idx = context.user_data['current_page'] * items_per_page
                end_idx = start_idx + items_per_page
                current_page_drugs = target_drugs[start_idx:end_idx]
                
                # اضافه کردن داروهای صفحه فعلی
                for drug in current_page_drugs:
                    keyboard.append([f"💊 {drug['name']} - {drug['price']}"])
                
                # اضافه کردن دکمه‌های صفحه‌بندی اگر نیاز باشد
                pagination_buttons = []
                if context.user_data['current_page'] > 0:
                    pagination_buttons.append("⬅️ صفحه قبل")
                if context.user_data['current_page'] < total_pages - 1:
                    pagination_buttons.append("➡️ صفحه بعد")
                
                if pagination_buttons:
                    keyboard.append(pagination_buttons)
                
                # اضافه کردن دکمه‌های ناوبری
                keyboard.append(["🔙 بازگشت به نتایج جستجو"])
                keyboard.append(["📤 ارسال پیشنهاد تبادل"])
                
                reply_markup = ReplyKeyboardMarkup(
                    keyboard, 
                    resize_keyboard=True,
                    one_time_keyboard=False  # برای صفحه‌بندی بهتر است one_time_keyboard=False باشد
                )
                
                await query.edit_message_text(
                    f"🏥 داروخانه: {pharmacy['pharmacy_name']}\n\n"
                    f"📄 صفحه {context.user_data['current_page'] + 1} از {total_pages}\n\n"
                    "لطفا داروی مورد نظر را از کیبرد زیر انتخاب کنید:",
                    reply_markup=None  # حذف کیبرد اینلاین
                )
                
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="داروهای موجود در این داروخانه:",
                    reply_markup=reply_markup
                )
                
                return States.SELECT_DRUGS
                
        except Exception as e:
            logger.error(f"خطا در دریافت داروها: {str(e)}")
            await query.edit_message_text("خطا در دریافت لیست داروها.")
            return States.SEARCH_DRUG
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in select_pharmacy: {str(e)}")
        await query.edit_message_text("خطایی در پردازش رخ داد.")
        return ConversationHandler.END
async def handle_drug_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت انتخاب دارو و صفحه‌بندی"""
    user_input = update.message.text
    
    # بررسی دکمه‌های صفحه‌بندی
    if user_input == "⬅️ صفحه قبل":
        context.user_data['current_page'] -= 1
        return await select_pharmacy(update, context)
    elif user_input == "➡️ صفحه بعد":
        context.user_data['current_page'] += 1
        return await select_pharmacy(update, context)
    elif user_input == "🔙 بازگشت به نتایج جستجو":
        # بازگشت به نتایج جستجو
        context.user_data.pop('current_page', None)
        return await search_drug(update, context)
    elif user_input == "📤 ارسال پیشنهاد تبادل":
        # ارسال پیشنهاد تبادل
        return await submit_offer(update, context)
    else:
        # پردازش انتخاب دارو
        try:
            # پیدا کردن داروی انتخاب شده
            drug_name = user_input.split(' - ')[0][2:]  # حذف emoji و جداکننده
            target_drugs = context.user_data.get('target_drugs', [])
            
            selected_drug = next((d for d in target_drugs if d['name'] == drug_name), None)
            
            if selected_drug:
                context.user_data['selected_drug'] = {
                    'id': selected_drug['id'],
                    'name': selected_drug['name'],
                    'price': selected_drug['price'],
                    'max_quantity': selected_drug['quantity'],
                    'type': 'target'
                }
                
                await update.message.reply_text(
                    f"💊 داروی انتخاب شده: {selected_drug['name']}\n"
                    f"💰 قیمت: {selected_drug['price']}\n\n"
                    f"لطفا تعداد مورد نیاز را وارد کنید (حداکثر {selected_drug['quantity']}):",
                    reply_markup=ReplyKeyboardRemove()
                )
                
                return States.SELECT_QUANTITY
            else:
                await update.message.reply_text("دارو یافت نشد. لطفا دوباره انتخاب کنید.")
                return States.SELECT_DRUGS
                
        except Exception as e:
            logger.error(f"Error in handle_drug_selection: {e}")
            await update.message.reply_text("خطایی در پردازش انتخاب دارو رخ داد.")
            return States.SELECT_DRUGS
# This should be at the top level, not inside any try/except block
async def show_drug_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش داروها به صورت دکمه‌های قابل انتخاب"""
    target_drugs = context.user_data.get('target_drugs', [])
    my_drugs = context.user_data.get('my_drugs', [])
    selected_items = context.user_data.get('selected_items', {'target': [], 'mine': []})
    
    # ایجاد دکمه‌های داروهای داروخانه مقابل
    # در تابع show_drug_buttons:
    target_buttons = []
    for drug in target_drugs:
        display_text = f"{format_button_text(drug['name'])}\nقیمت: {format_button_text(drug['price'])}"
        is_selected = any(item['id'] == drug['id'] for item in selected_items['target'])
        target_buttons.append([InlineKeyboardButton(
        f"{'✅ ' if is_selected else '◻️ '}{display_text}",
        callback_data=f"select_target_{drug['id']}"
        )])

    my_buttons = []
    for drug in my_drugs:
        display_text = f"{format_button_text(drug['name'])}\nقیمت: {format_button_text(drug['price'])}"
        is_selected = any(item['id'] == drug['id'] for item in selected_items['mine'])
        my_buttons.append([InlineKeyboardButton(
        f"{'✅ ' if is_selected else '◻️ '}{display_text}",
        callback_data=f"select_mine_{drug['id']}"
        )])
    # ایجاد صفحه بندی اگر داروها زیاد باشند
    keyboard = [
        [InlineKeyboardButton("--- داروهای مقابل ---", callback_data="none")],
        *target_buttons[:5],  # حداکثر 5 دارو در هر صفحه
        [InlineKeyboardButton("--- داروهای من ---", callback_data="none")],
        *my_buttons[:5],
        [
            InlineKeyboardButton("📤 ارسال پیشنهاد", callback_data="submit_offer"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_pharmacies")
        ]
    ]
    
    # نمایش داروهای انتخاب شده
    message = "📋 داروها را انتخاب کنید:\n\n"
    if selected_items['target']:
        message += "از داروخانه مقابل:\n"
        for item in selected_items['target']:
            message += f"✅ {item['name']} (تعداد: {item['quantity']})\n"
    
    if selected_items['mine']:
        message += "\nاز داروهای شما:\n"
        for item in selected_items['mine']:
            message += f"✅ {item['name']} (تعداد: {item['quantity']})\n"
    
    if not selected_items['target'] and not selected_items['mine']:
        message += "هنوز دارویی انتخاب نکرده‌اید."
    
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"خطا در نمایش دکمه‌ها: {str(e)}")


async def select_drug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drug selection for offer"""
    try:
        query = update.callback_query
        await query.answer()

        if query.data == "back_to_items":
            return await show_drug_buttons(update, context)
            
        if query.data.startswith("select_target_"):
            drug_id = int(query.data.split('_')[2])
            
            # Find the drug in target drugs
            target_drugs = context.user_data.get('target_drugs', [])
            selected_drug = next((item for item in target_drugs if item['id'] == drug_id), None)
            
            if selected_drug:
                context.user_data['current_drug'] = {
                    'id': selected_drug['id'],
                    'name': selected_drug['name'],
                    'price': selected_drug['price'],
                    'max_quantity': selected_drug['quantity'],
                    'type': 'target'
                }
                await query.edit_message_text(
                    f"تعداد مورد نیاز برای {selected_drug['name']} را وارد کنید (حداکثر: {selected_drug['quantity']}):",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_selection")]
                    ])
                )
                return States.SELECT_QUANTITY
        
        elif query.data.startswith("select_mine_"):
            drug_id = int(query.data.split('_')[2])
            
            # Find the drug in my items
            my_drugs = context.user_data.get('my_drugs', [])
            selected_drug = next((item for item in my_drugs if item['id'] == drug_id), None)
            
            if selected_drug:
                context.user_data['current_drug'] = {
                    'id': selected_drug['id'],
                    'name': selected_drug['name'],
                    'price': selected_drug['price'],
                    'max_quantity': selected_drug['quantity'],
                    'type': 'mine'
                }
                await query.edit_message_text(
                    f"تعداد مورد نظر برای {selected_drug['name']} را وارد کنید (حداکثر: {selected_drug['quantity']}):",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_selection")]
                    ])
                )
                return States.SELECT_QUANTITY
        
        elif query.data == "submit_offer":
            return await submit_offer(update, context)
        
        elif query.data == "back":
            return await handle_back(update, context)
        
        elif query.data == "back_to_selection":
            return await show_drug_buttons(update, context)
            
    except Exception as e:
        logger.error(f"Error in select_drug: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
async def show_drug_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, is_target: bool):
    """نمایش لیست داروها برای انتخاب"""
    drug_list = context.user_data['target_drugs'] if is_target else context.user_data['my_drugs']
    selected_items = context.user_data['selected_items']['target'] if is_target else context.user_data['selected_items']['mine']
    
    keyboard = []
    for drug in drug_list:
        # بررسی آیا دارو قبلا انتخاب شده
        is_selected = any(item['id'] == drug['id'] for item in selected_items)
        
        keyboard.append([InlineKeyboardButton(
            f"{'✅ ' if is_selected else '◻️ '}{drug['name']}",
            callback_data=f"select_{'target' if is_target else 'mine'}_{drug['id']}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_list")])
    
    await update.callback_query.edit_message_text(
        f"لطفا دارو{'های داروخانه مقابل' if is_target else 'های خود'} را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def select_drug_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت تعداد برای داروی انتخاب شده"""
    query = update.callback_query
    await query.answer()

    if query.data == "back_to_list":
        return await select_pharmacy(update, context)
        
    parts = query.data.split('_')
    drug_id = int(parts[2])
    is_target = parts[1] == 'target'
    
    # پیدا کردن داروی انتخاب شده
    drug_list = context.user_data['target_drugs'] if is_target else context.user_data['my_drugs']
    selected_drug = next((drug for drug in drug_list if drug['id'] == drug_id), None)
    
    if selected_drug:
        context.user_data['current_selection'] = {
            'drug': selected_drug,
            'is_target': is_target
        }
        
        await query.edit_message_text(
            f"لطفا تعداد مورد نظر برای {selected_drug['name']} را وارد کنید (موجودی: {selected_drug['quantity']}):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_selection")]])
        )
        return States.ENTER_QUANTITY

async def enter_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quantity input for selected drug"""
    try:
        quantity = int(update.message.text)
        current_drug = context.user_data.get('current_drug')
        
        if not current_drug:
            await update.message.reply_text("اطلاعات دارو یافت نشد. لطفا دوباره تلاش کنید.")
            return ConversationHandler.END
            
        if quantity <= 0:
            await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید.")
            return States.SELECT_QUANTITY
            
        if quantity > current_drug['max_quantity']:
            await update.message.reply_text(f"موجودی کافی نیست. حداکثر تعداد قابل انتخاب: {current_drug['max_quantity']}")
            return States.SELECT_QUANTITY
        
        # Save the selected quantity
        drug_type = current_drug['type']
        selected_items = context.user_data['selected_items'][drug_type]
        
        # Remove if already exists
        selected_items = [item for item in selected_items if item['id'] != current_drug['id']]
        
        # Add new selection
        selected_items.append({
            'id': current_drug['id'],
            'name': current_drug['name'],
            'price': current_drug['price'],
            'quantity': quantity
        })
        
        context.user_data['selected_items'][drug_type] = selected_items
        
        # Return to drug selection
        return await show_drug_buttons(update, context)
        
    except ValueError:
        await update.message.reply_text("لطفا یک عدد صحیح وارد کنید.")
        return States.SELECT_QUANTITY

async def submit_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle offer submission"""
    try:
        query = update.callback_query
        await query.answer()

        # Get selected items from context
        selected_items = context.user_data.get('selected_items', {'target': [], 'mine': []})
        
        # Check if any items are selected
        if not selected_items['target'] and not selected_items['mine']:
            await query.answer("هیچ دارویی انتخاب نشده است!", show_alert=True)
            return States.SELECT_DRUGS

        # Calculate totals using parse_price
        target_total = sum(parse_price(item['price']) * item['quantity'] for item in selected_items['target'])
        my_total = sum(parse_price(item['price']) * item['quantity'] for item in selected_items['mine'])
        
        # Prepare message
        message = "📋 خلاصه پیشنهاد تبادل:\n\n"
        if selected_items['target']:
            message += "📌 از داروخانه مقابل:\n"
            for item in selected_items['target']:
                message += f"- {item['name']} ({item['quantity']} عدد) - {item['price']}\n"
            message += f"💰 جمع کل: {target_total:,.0f}\n\n"
        
        if selected_items['mine']:
            message += "📌 از داروهای شما:\n"
            for item in selected_items['mine']:
                message += f"- {item['name']} ({item['quantity']} عدد) - {item['price']}\n"
            message += f"💰 جمع کل: {my_total:,.0f}\n\n"
        
        if target_total != my_total:
            message += f"⚠️ توجه: اختلاف قیمت {abs(target_total - my_total):,.0f} تومان\n\n"
        
        message += "آیا مایل به ارسال این پیشنهاد هستید؟"
        
        keyboard = [
            [InlineKeyboardButton("✅ تأیید و ارسال", callback_data="confirm_offer")],
            [InlineKeyboardButton("✏️ ویرایش", callback_data="back_to_selection")]
        ]
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard))
        
        return States.CONFIRM_OFFER
        
    except Exception as e:
        logger.error(f"Error in submit_offer: {e}")
        await query.edit_message_text("خطایی در ارسال پیشنهاد رخ داد.")
        return States.SELECT_DRUGS
async def handle_offer_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle drug selection for offer"""
    try:
        query = update.callback_query
        await query.answer()

        if query.data == "back_to_pharmacies":
            # Rebuild pharmacy selection keyboard
            pharmacies = context.user_data.get('pharmacies', {})
            keyboard = []
            for pharmacy_id, pharmacy_data in pharmacies.items():
                keyboard.append([InlineKeyboardButton(
                    f"🏥 {pharmacy_data['name']} ({pharmacy_data['count']} دارو)", 
                    callback_data=f"pharmacy_{pharmacy_id}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back")])
            
            await query.edit_message_text(
                "لطفا داروخانه مورد نظر را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return States.SELECT_PHARMACY
            
        if not query.data.startswith("offer_"):
            await query.edit_message_text("خطا در انتخاب دارو.")
            return States.SELECT_ITEMS
            
        drug_id = int(query.data.split("_")[1])
        pharmacy_items = context.user_data['selected_pharmacy']['items']
        selected_item = next((item for item in pharmacy_items if item['id'] == drug_id), None)
        
        if not selected_item:
            await query.edit_message_text("دارو یافت نشد.")
            return States.SELECT_ITEMS
            
        context.user_data['selected_item'] = selected_item
        
        keyboard = [
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_items")]
        ]
        
        await query.edit_message_text(
            f"💊 دارو: {selected_item['name']}\n"
            f"💰 قیمت: {selected_item['price']}\n"
            f"📅 تاریخ انقضا: {selected_item['date']}\n"
            f"📦 موجودی: {selected_item['quantity']}\n\n"
            "لطفا تعداد مورد نیاز را وارد کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.SELECT_QUANTITY
    except Exception as e:
        logger.error(f"Error in handle_offer_response: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def select_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Select quantity for drug offer"""
    try:
        if update.callback_query and update.callback_query.data == "back_to_items":
            await update.callback_query.answer()
            pharmacy = context.user_data.get('selected_pharmacy', {})
            
            # Rebuild items keyboard
            keyboard = []
            for item in pharmacy.get('items', []):
                keyboard.append([InlineKeyboardButton(
                    f"{item['name']} - {item['price']} (موجودی: {item['quantity']})",
                    callback_data=f"offer_{item['id']}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت به نتایج", callback_data="back_to_pharmacies")])
            
            await update.callback_query.edit_message_text(
                f"🏥 داروخانه: {pharmacy.get('name', '')}\n\n"
                "لطفا داروی مورد نظر را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return States.SELECT_ITEMS
            
        try:
            quantity = int(update.message.text)
            selected_item = context.user_data.get('selected_item')
            
            if not selected_item:
                await update.message.reply_text("اطلاعات دارو یافت نشد.")
                return States.SEARCH_DRUG
                
            if quantity <= 0:
                await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید.")
                return States.SELECT_QUANTITY
                
            if quantity > selected_item['quantity']:
                await update.message.reply_text(
                    f"موجودی کافی نیست. حداکثر تعداد قابل انتخاب: {selected_item['quantity']}"
                )
                return States.SELECT_QUANTITY
                
            context.user_data['selected_quantity'] = quantity
            
            keyboard = [
                [InlineKeyboardButton("✅ تایید", callback_data="confirm_offer")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_items")]
            ]
            
            await update.message.reply_text(
                f"💊 دارو: {selected_item['name']}\n"
                f"💰 قیمت واحد: {selected_item['price']}\n"
                f"📦 تعداد: {quantity}\n"
                f"💵 مبلغ کل: {parse_price(selected_item['price']) * quantity}\n\n"
                "آیا از انتخاب خود مطمئن هستید؟",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return States.CONFIRM_OFFER
                
        except ValueError:
            await update.message.reply_text("لطفا یک عدد صحیح وارد کنید.")
            return States.SELECT_QUANTITY
    except Exception as e:
        logger.error(f"Error in select_quantity: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
async def select_exchange_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle selection of items for exchange"""
    try:
        query = update.callback_query
        await query.answer()

        if query.data == "back_to_pharmacies":
            return await select_pharmacy(update, context)
            
        if query.data == "send_exchange":
            return await confirm_exchange(update, context)
            
        if query.data.startswith("select_pharma_"):
            drug_id = int(query.data.split("_")[2])
            
            # Find the drug in pharmacy items
            pharmacy = context.user_data['selected_pharmacy']
            selected_drug = next((item for item in pharmacy['items'] if item['id'] == drug_id), None)
            
            if selected_drug:
                # Toggle selection
                if any(d['id'] == drug_id for d in context.user_data['selected_drugs']):
                    context.user_data['selected_drugs'] = [
                        d for d in context.user_data['selected_drugs'] if d['id'] != drug_id
                    ]
                else:
                    context.user_data['selected_drugs'].append(selected_drug)
                
                return await select_pharmacy(update, context)
                
        elif query.data.startswith("select_mine_"):
            drug_id = int(query.data.split("_")[2])
            
            # Find the drug in my items
            my_drugs = context.user_data['my_drugs']
            selected_drug = next((item for item in my_drugs if item['id'] == drug_id), None)
            
            if selected_drug:
                # Toggle selection
                if any(d['id'] == drug_id for d in context.user_data['my_drugs']):
                    context.user_data['my_drugs'] = [
                        d for d in context.user_data['my_drugs'] if d['id'] != drug_id
                    ]
                else:
                    context.user_data['my_drugs'].append(selected_drug)
                
                return await select_pharmacy(update, context)
                
    except Exception as e:
        logger.error(f"Error in select_exchange_items: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def confirm_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm the exchange and show summary"""
    try:
        query = update.callback_query
        await query.answer()

        selected_pharma_drugs = context.user_data.get('selected_drugs', [])
        selected_my_drugs = context.user_data.get('my_drugs', [])
        
        if not selected_pharma_drugs and not selected_my_drugs:
            await query.answer("هیچ دارویی انتخاب نشده است.", show_alert=True)
            return
            
        # Calculate totals
        pharma_total = sum(parse_price(d['price']) for d in selected_pharma_drugs)
        my_total = sum(parse_price(d['price']) for d in selected_my_drugs)
        difference = pharma_total - my_total
        
        # Prepare message
        message = "📋 خلاصه پیشنهاد تبادل:\n\n"
        
        message += "📌 داروهای انتخابی از داروخانه مقابل:\n"
        for item in selected_pharma_drugs:
            message += f"- {item['name']} ({item['price']})\n"
        message += f"💰 جمع کل: {pharma_total}\n\n"
        
        message += "📌 داروهای انتخابی از شما:\n"
        for item in selected_my_drugs:
            message += f"- {item['name']} ({item['price']})\n"
        message += f"💰 جمع کل: {my_total}\n\n"
        
        if difference != 0:
            message += f"🔀 اختلاف قیمت: {abs(difference)} ({'به نفع شما' if difference < 0 else 'به نفع داروخانه مقابل'})\n\n"
        
        message += "آیا مایل به ارسال این پیشنهاد هستید؟"
        
        keyboard = [
            [InlineKeyboardButton("✅ تأیید و ارسال", callback_data="send_exchange_final")],
            [InlineKeyboardButton("✏️ ویرایش", callback_data="back_to_selection")]
        ]
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.CONFIRM_EXCHANGE
        
    except Exception as e:
        logger.error(f"Error in confirm_exchange: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def send_exchange_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the exchange offer to the pharmacy"""
    try:
        query = update.callback_query
        await query.answer()

        selected_pharma_drugs = context.user_data.get('selected_drugs', [])
        selected_my_drugs = context.user_data.get('my_drugs', [])
        pharmacy_id = context.user_data.get('selected_pharmacy_id')
        
        if not selected_pharma_drugs or not pharmacy_id:
            await query.edit_message_text("اطلاعات ناقص است.")
            return States.SEARCH_DRUG
            
        # Calculate totals
        pharma_total = sum(parse_price(d['price']) for d in selected_pharma_drugs)
        my_total = sum(parse_price(d['price']) for d in selected_my_drugs)
        difference = pharma_total - my_total
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Create exchange record
                cursor.execute('''
                INSERT INTO exchanges (
                    from_pharmacy_id, to_pharmacy_id, 
                    from_total, to_total, difference, 
                    status
                ) VALUES (%s, %s, %s, %s, %s, 'pending')
                RETURNING id
                ''', (
                    update.effective_user.id,
                    pharmacy_id,
                    my_total,
                    pharma_total,
                    difference
                ))
                exchange_id = cursor.fetchone()[0]
                
                # Add pharmacy drugs
                for item in selected_pharma_drugs:
                    cursor.execute('''
                    INSERT INTO exchange_items (
                        exchange_id, drug_id, drug_name, price, 
                        quantity, from_pharmacy
                    ) VALUES (%s, %s, %s, %s, %s, FALSE)
                    ''', (
                        exchange_id,
                        item['id'],
                        item['name'],
                        item['price'],
                        1  # Default quantity
                    ))
                
                # Add my drugs
                for item in selected_my_drugs:
                    cursor.execute('''
                    INSERT INTO exchange_items (
                        exchange_id, drug_id, drug_name, price, 
                        quantity, from_pharmacy
                    ) VALUES (%s, %s, %s, %s, %s, TRUE)
                    ''', (
                        exchange_id,
                        item['id'],
                        item['name'],
                        item['price'],
                        1  # Default quantity
                    ))
                
                conn.commit()
                
                # Notify pharmacy
                try:
                    message = "📬 پیشنهاد تبادل جدید دریافت شد:\n\n"
                    
                    message += "📌 داروهای پیشنهادی از شما:\n"
                    for item in selected_pharma_drugs:
                        message += f"- {item['name']} ({item['price']})\n"
                    message += f"💰 جمع کل: {pharma_total}\n\n"
                    
                    message += "📌 داروهای پیشنهادی از طرف مقابل:\n"
                    for item in selected_my_drugs:
                        message += f"- {item['name']} ({item['price']})\n"
                    message += f"💰 جمع کل: {my_total}\n\n"
                    
                    if difference != 0:
                        message += f"🔀 اختلاف قیمت: {abs(difference)} ({'به نفع شما' if difference > 0 else 'به نفع طرف مقابل'})\n\n"
                    
                    keyboard = [
                        [InlineKeyboardButton("✅ تأیید تبادل", callback_data=f"accept_exchange_{exchange_id}")],
                        [InlineKeyboardButton("❌ رد تبادل", callback_data=f"reject_exchange_{exchange_id}")]
                    ]
                    
                    await context.bot.send_message(
                        chat_id=pharmacy_id,
                        text=message,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    
                    await query.edit_message_text(
                        "✅ پیشنهاد تبادل شما با موفقیت ارسال شد!\n\n"
                        "پس از تأیید داروخانه، جزئیات نهایی به شما اعلام خواهد شد."
                    )
                except Exception as e:
                    logger.error(f"Failed to notify pharmacy: {e}")
                    await query.edit_message_text(
                        "✅ پیشنهاد شما ثبت شد اما خطا در اطلاع‌رسانی به داروخانه رخ داد.\n"
                        "لطفا با داروخانه تماس بگیرید."
                    )
                
        except Exception as e:
            logger.error(f"Error saving exchange: {e}")
            if conn:
                conn.rollback()
            await query.edit_message_text("خطا در ثبت پیشنهاد تبادل. لطفا دوباره تلاش کنید.")
        finally:
            if conn:
                conn.close()
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in send_exchange_final: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def confirm_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm and send the offer"""
    try:
        query = update.callback_query
        await query.answer()

        selected_items = context.user_data.get('selected_items', {'target': [], 'mine': []})
        pharmacy_id = context.user_data.get('selected_pharmacy_id')
        
        if not pharmacy_id or (not selected_items['target'] and not selected_items['mine']):
            await query.edit_message_text("اطلاعات ناقص است. لطفا دوباره تلاش کنید.")
            return States.SEARCH_DRUG

        # Calculate totals using parse_price
        target_total = sum(parse_price(item['price']) * item['quantity'] for item in selected_items['target'])
        my_total = sum(parse_price(item['price']) * item['quantity'] for item in selected_items['mine'])
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Create offer record
                cursor.execute('''
                INSERT INTO offers (pharmacy_id, buyer_id, total_price, status)
                VALUES (%s, %s, %s, 'pending')
                RETURNING id
                ''', (pharmacy_id, update.effective_user.id, target_total))
                offer_id = cursor.fetchone()[0]
                
                # Add offer items
                for item in selected_items['target']:
                    cursor.execute('''
                    INSERT INTO offer_items (offer_id, drug_name, price, quantity)
                    VALUES (%s, %s, %s, %s)
                    ''', (offer_id, item['name'], item['price'], item['quantity']))
                
                # Add compensation items if any
                for item in selected_items['mine']:
                    cursor.execute('''
                    INSERT INTO compensation_items (offer_id, drug_id, quantity)
                    VALUES (%s, %s, %s)
                    ''', (offer_id, item['id'], item['quantity']))
                
                conn.commit()
                
                # Notify pharmacy
                try:
                    # در تابع confirm_offer:
                    # در تابع confirm_offer:
                    message = "📋 خلاصه پیشنهاد تبادل:\n\n"
                    if selected_items['target']:
                        message += "📌 داروهای درخواستی:\n"
                        for item in selected_items['target']:
                            message += f"- {item['name']} ({item['quantity']} عدد) - {item['price']}\n"
                        message += f"💰 جمع کل: {target_total:,.0f}\n\n"

                    if selected_items['mine']:
                        message += "📌 داروهای پیشنهادی:\n"
                        for item in selected_items['mine']:
                            message += f"- {item['name']} ({item['quantity']} عدد)\n"
                    keyboard = [
                        [InlineKeyboardButton("✅ تأیید پیشنهاد", callback_data=f"accept_{offer_id}")],
                        [InlineKeyboardButton("❌ رد پیشنهاد", callback_data=f"reject_{offer_id}")]
                    ]
                    
                    await context.bot.send_message(
                        chat_id=pharmacy_id,
                        text=message,
                        reply_markup=InlineKeyboardMarkup(keyboard))
                    
                    await query.edit_message_text(
                        "✅ پیشنهاد شما با موفقیت ارسال شد!\n\n"
                        "پس از تأیید داروخانه، جزئیات نهایی به شما اعلام خواهد شد.")
                except Exception as e:
                    logger.error(f"Failed to notify pharmacy: {e}")
                    await query.edit_message_text(
                        "پیشنهاد شما ثبت شد اما خطا در اطلاع‌رسانی به داروخانه رخ داد.\n"
                        "لطفا با داروخانه تماس بگیرید.")
                
        except Exception as e:
            logger.error(f"Error saving offer: {e}")
            if conn:
                conn.rollback()
            await query.edit_message_text("خطا در ثبت پیشنهاد. لطفا دوباره تلاش کنید.")
        finally:
            if conn:
                conn.close()
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in confirm_offer: {e}")
        await query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return States.CONFIRM_OFFER
async def show_two_column_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show two-column selection for items and compensation"""
    try:
        query = update.callback_query
        await query.answer()

        offer_items = context.user_data.get('offer_items', [])
        comp_items = context.user_data.get('comp_items', [])
        
        # Prepare items message
        items_msg = "📋 لیست داروهای انتخاب شده:\n\n"
        total_price = 0
        
        for idx, item in enumerate(offer_items, 1):
            item_price = parse_price(item['price']) * item['quantity']
            total_price += item_price
            items_msg += (
                f"{idx}. {item['drug_name']}\n"
                f"   تعداد: {item['quantity']}\n"
                f"   قیمت: {item['price']} (جمع: {item_price})\n\n"
            )
        
        # Prepare compensation message
        comp_msg = "📋 لیست جبرانی:\n\n"
        if comp_items:
            for idx, item in enumerate(comp_items, 1):
                comp_msg += (
                    f"{idx}. {item['name']}\n"
                    f"   تعداد: {item['quantity']}\n\n"
                )
        else:
            comp_msg += "هیچ موردی انتخاب نشده است.\n\n"
        
        # Calculate totals
        totals_msg = (
            f"💰 جمع کل: {total_price}\n"
            f"💵 مبلغ قابل پرداخت: {total_price}\n\n"
        )
        
        # Prepare keyboard
        keyboard = [
            [InlineKeyboardButton("➕ افزودن داروی دیگر", callback_data="add_more")],
            [InlineKeyboardButton("💵 پرداخت نقدی", callback_data="compensate")],
            [InlineKeyboardButton("📝 ویرایش انتخاب‌ها", callback_data="edit_selection")],
            [InlineKeyboardButton("✅ تایید نهایی", callback_data="confirm_totals")]
        ]
        
        await query.edit_message_text(
            f"{items_msg}\n{comp_msg}\n{totals_msg}"
            "لطفا گزینه مورد نظر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.CONFIRM_TOTALS
    except Exception as e:
        logger.error(f"Error in show_two_column_selection: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def handle_compensation_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle compensation selection (cash or items)"""
    try:
        query = update.callback_query
        await query.answer()

        if query.data == "add_more":
            await query.edit_message_text("لطفا نام دارویی که می‌خواهید جستجو کنید را وارد کنید:")
            return States.SEARCH_DRUG
            
        if query.data == "compensate":
            # User selected cash payment
            context.user_data['comp_method'] = 'cash'
            return await confirm_totals(update, context)
            
        if query.data.startswith("comp_"):
            # Handle item selection for compensation
            drug_id = int(query.data.split("_")[1])
            
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                    cursor.execute('''
                    SELECT id, name, quantity 
                    FROM drug_items 
                    WHERE id = %s AND user_id = %s AND quantity > 0
                    ''', (drug_id, update.effective_user.id))
                    drug = cursor.fetchone()
                    
                    if not drug:
                        await query.answer("دارو یافت نشد.", show_alert=True)
                        return
                    
                    context.user_data['comp_drug'] = dict(drug)
                    await query.edit_message_text(
                        f"💊 داروی انتخابی برای جبران: {drug['name']}\n"
                        f"📦 موجودی: {drug['quantity']}\n\n"
                        "لطفا تعداد مورد نظر را وارد کنید:"
                    )
                    return States.COMPENSATION_QUANTITY
                    
            except Exception as e:
                logger.error(f"Error getting drug for compensation: {e}")
                await query.answer("خطا در دریافت اطلاعات دارو.", show_alert=True)
            finally:
                if conn:
                    conn.close()
    except Exception as e:
        logger.error(f"Error in handle_compensation_selection: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
async def save_compensation_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save compensation item quantity"""
    try:
        quantity = int(update.message.text)
        item_index = context.user_data.get('editing_comp_item_index')
        compensation_items = context.user_data.get('compensation_items', [])
        
        if item_index is not None and item_index < len(compensation_items):
            compensation_items[item_index]['quantity'] = quantity
            context.user_data['compensation_items'] = compensation_items
            
            await update.message.reply_text(
                f"تعداد به {quantity} تنظیم شد.",
                reply_markup=ReplyKeyboardRemove()
            )
            
            return await handle_compensation_selection(update, context)
        else:
            await update.message.reply_text("خطا در ذخیره تعداد. لطفا دوباره تلاش کنید.")
            return States.COMPENSATION_QUANTITY
            
    except ValueError:
        await update.message.reply_text("لطفا یک عدد معتبر وارد کنید.")
        return States.COMPENSATION_QUANTITY

async def confirm_totals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm final totals and create offer"""
    try:
        query = update.callback_query
        await query.answer()

        offer_items = context.user_data.get('offer_items', [])
        if not offer_items:
            await query.edit_message_text("هیچ دارویی انتخاب نشده است.")
            return States.SEARCH_DRUG
            
        # Calculate total price
        total_price = sum(parse_price(item['price']) * item['quantity'] for item in offer_items)
        
        # Prepare message
        message = "📋 خلاصه پیشنهاد:\n\n"
        message += "📌 داروهای درخواستی:\n"
        for item in offer_items:
            message += f"- {item['drug_name']} ({item['quantity']} عدد) - {item['price']}\n"
        
        message += f"\n💰 جمع کل: {total_price}\n"
        
        # Add compensation info
        if context.user_data.get('comp_method') == 'cash':
            message += "\n💵 روش جبران: پرداخت نقدی\n"
        elif context.user_data.get('comp_items'):
            message += "\n💊 داروهای جبرانی:\n"
            for item in context.user_data['comp_items']:
                message += f"- {item['name']} ({item['quantity']} عدد)\n"
        
        keyboard = [
            [InlineKeyboardButton("✅ تأیید و ارسال", callback_data="send_offer")],
            [InlineKeyboardButton("✏️ ویرایش", callback_data="edit_selection")]
        ]
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.CONFIRM_TOTALS
    except Exception as e:
        logger.error(f"Error in confirm_totals: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def send_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the finalized offer to the pharmacy"""
    try:
        query = update.callback_query
        await query.answer()

        offer_items = context.user_data.get('offer_items', [])
        if not offer_items:
            await query.edit_message_text("هیچ دارویی برای ارسال وجود ندارد.")
            return States.SEARCH_DRUG
            
        # Get pharmacy ID from first item (all should be same pharmacy)
        pharmacy_id = offer_items[0]['pharmacy_id']
        buyer_id = update.effective_user.id
        
        # Calculate total price
        total_price = sum(parse_price(item['price']) * item['quantity'] for item in offer_items)
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Create offer record
                cursor.execute('''
                INSERT INTO offers (pharmacy_id, buyer_id, total_price)
                VALUES (%s, %s, %s)
                RETURNING id
                ''', (pharmacy_id, buyer_id, total_price))
                offer_id = cursor.fetchone()[0]
                
                # Add offer items
                for item in offer_items:
                    cursor.execute('''
                    INSERT INTO offer_items (offer_id, drug_name, price, quantity)
                    VALUES (%s, %s, %s, %s)
                    ''', (offer_id, item['drug_name'], item['price'], item['quantity']))
                
                # Add compensation items if any
                if context.user_data.get('comp_items'):
                    for item in context.user_data['comp_items']:
                        cursor.execute('''
                        INSERT INTO compensation_items (offer_id, drug_id, quantity)
                        VALUES (%s, %s, %s)
                        ''', (offer_id, item['id'], item['quantity']))
                
                conn.commit()
                
                # Notify pharmacy
                try:
                    keyboard = [
                        [InlineKeyboardButton("✅ تأیید پیشنهاد", callback_data=f"accept_{offer_id}")],
                        [InlineKeyboardButton("❌ رد پیشنهاد", callback_data=f"reject_{offer_id}")]
                    ]
                    
                    offer_message = "📬 پیشنهاد جدید دریافت شد:\n\n"
                    for item in offer_items:
                        offer_message += f"- {item['drug_name']} ({item['quantity']} عدد) - {item['price']}\n"
                    
                    offer_message += f"\n💰 جمع کل: {total_price}\n"
                    
                    if context.user_data.get('comp_method') == 'cash':
                        offer_message += "\n💵 روش جبران: پرداخت نقدی\n"
                    elif context.user_data.get('comp_items'):
                        offer_message += "\n💊 داروهای جبرانی:\n"
                        for item in context.user_data['comp_items']:
                            offer_message += f"- {item['name']} ({item['quantity']} عدد)\n"
                    
                    await context.bot.send_message(
                        chat_id=pharmacy_id,
                        text=offer_message,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    
                    await query.edit_message_text(
                        "✅ پیشنهاد شما با موفقیت ارسال شد!\n\n"
                        "پس از تأیید داروخانه با شما تماس گرفته خواهد شد."
                    )
                except Exception as e:
                    logger.error(f"Failed to notify pharmacy: {e}")
                    await query.edit_message_text(
                        "✅ پیشنهاد شما ثبت شد اما خطا در اطلاع‌رسانی به داروخانه رخ داد.\n"
                        "لطفا با داروخانه تماس بگیرید."
                    )
                
        except Exception as e:
            logger.error(f"Error saving offer: {e}")
            if conn:
                conn.rollback()
            await query.edit_message_text("خطا در ثبت پیشنهاد. لطفا دوباره تلاش کنید.")
        finally:
            if conn:
                conn.close()
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in send_offer: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def handle_match_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle match notification response"""
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
                SELECT di.id, di.name, di.price, di.date, di.quantity,
                       u.id as pharmacy_id, p.name as pharmacy_name
                FROM drug_items di
                JOIN users u ON di.user_id = u.id
                JOIN pharmacies p ON u.id = p.user_id
                WHERE di.id = %s
                ''', (drug_id,))
                drug = cursor.fetchone()
                
                # Get need details
                cursor.execute('''
                SELECT id, name, quantity 
                FROM user_needs 
                WHERE id = %s AND user_id = %s
                ''', (need_id, update.effective_user.id))
                need = cursor.fetchone()
                
                if not drug or not need:
                    await query.edit_message_text("اطلاعات یافت نشد.")
                    return
                
                context.user_data['match_drug'] = dict(drug)
                context.user_data['match_need'] = dict(need)
                
                keyboard = [
                    [InlineKeyboardButton("💊 مبادله این دارو", callback_data=f"exchange_{drug_id}")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
                ]
                
                # در تابع handle_match_notification:
                # در تابع handle_match_notification:
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
                
        except Exception as e:
            logger.error(f"Error handling match: {e}")
            await query.edit_message_text("خطا در دریافت اطلاعات تطابق.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in handle_match_notification: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
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

def main():
    """Start the bot"""
    try:
        # Initialize database
        asyncio.get_event_loop().run_until_complete(initialize_db())
        
        # Load drug data
        if not load_drug_data():
            logger.warning("Failed to load drug data - some features may not work")
        
        # Create application
        application = ApplicationBuilder().token("7584437136:AAFVtfF9RjCyteONcz8DSg2F2CfhgQT2GcQ").build()
        
        # Add conversation handler for admin verification process
        admin_verify_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(admin_verify_start, pattern="^admin_verify$")
            ],
            states={
                States.REGISTER_PHONE: [
                    MessageHandler(filters.CONTACT | filters.TEXT, receive_phone_for_admin_verify)
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            allow_reentry=True
        )
        
        # Add conversation handler with registration states (normal registration)
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
            fallbacks=[CommandHandler('cancel', cancel)],
            allow_reentry=True
        )
        
        # Add conversation handler for simple verification
        simple_verify_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(simple_verify_start, pattern="^simple_verify$")
            ],
            states={
                States.SIMPLE_VERIFICATION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, simple_verify_code)
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            allow_reentry=True
        )
        
        # Add conversation handler for personnel login
        personnel_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(personnel_login_start, pattern="^personnel_login$")
            ],
            states={
                States.PERSONNEL_LOGIN: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, verify_personnel_code)
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            allow_reentry=True
        )
        
        # Add all handlers
        application.add_handler(CommandHandler('start', start))
        application.add_handler(admin_verify_handler)
        application.add_handler(registration_handler)
        application.add_handler(simple_verify_handler)
        application.add_handler(personnel_handler)
        application.add_handler(MessageHandler(filters.Regex('^ساخت کد پرسنل$'), generate_personnel_code))
        

        
        
        # Add conversation handler for drug management
        drug_handler = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex('^اضافه کردن دارو$'), add_drug_item),
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
                    CallbackQueryHandler(add_drug_item, pattern="^back$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, search_drug_for_adding)
                ],
                States.SELECT_DRUG_FOR_ADDING: [
                    CallbackQueryHandler(select_drug_for_adding, pattern="^select_drug_|back_to_drug_selection$")
                ],
                States.ADD_DRUG_DATE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, add_drug_date),
                    CallbackQueryHandler(search_drug_for_adding, pattern="^back_to_search$")
                ],
                States.ADD_DRUG_QUANTITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_drug_item),
                    CallbackQueryHandler(select_drug_for_adding, pattern="^back_to_drug_selection$")
                ],
                States.EDIT_DRUG: [
                    CallbackQueryHandler(edit_drugs, pattern="^back_to_list$"),
                    CallbackQueryHandler(edit_drug_item, pattern="^edit_drug_"),
                    CallbackQueryHandler(handle_drug_edit_action, pattern="^(edit_date|edit_quantity|delete_drug)$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_drug_edit),
                    CallbackQueryHandler(handle_drug_deletion, pattern="^(confirm_delete|cancel_delete)$")
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            allow_reentry=True
        )
        
        # Add conversation handler for needs management
        needs_handler = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex('^ثبت نیاز جدید$'), add_need),
                MessageHandler(filters.Regex('^لیست نیازهای من$'), list_my_needs),
                CallbackQueryHandler(edit_needs, pattern="^edit_needs$"),
                CallbackQueryHandler(edit_need_item, pattern="^edit_need_"),
                CallbackQueryHandler(handle_need_edit_action, pattern="^(edit_need_name|edit_need_desc|edit_need_quantity|delete_need)$"),
                CallbackQueryHandler(handle_need_deletion, pattern="^(confirm_need_delete|cancel_need_delete)$")
            ],
            states={
                States.ADD_NEED_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_need_name)
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
            fallbacks=[CommandHandler('cancel', cancel)],
            allow_reentry=True
        )
        
        # Add conversation handler for search and trade
        trade_handler = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex(r'^جستجوی دارو$'), search_drug),
                CallbackQueryHandler(handle_match_notification, pattern=r'^view_match_')
            ],
            states={
                States.SEARCH_DRUG: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search)
            ],
                States.SELECT_PHARMACY: [
                    CallbackQueryHandler(select_pharmacy, pattern=r'^pharmacy_\d+$')
            ],
                States.SELECT_DRUGS: [
                    MessageHandler(filters.Regex(r'^select_target_\d+$'), select_drug),
                    MessageHandler(filters.Regex(r'^select_mine_\d+$'), select_drug),
                    MessageHandler(filters.Regex(r'^submit_offer$'), submit_offer),
                    MessageHandler(filters.Regex(r'^back$'), handle_back)
           ],
                States.SELECT_QUANTITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, enter_quantity),
                    CallbackQueryHandler(show_drug_buttons, pattern=r'^back_to_selection$')
           ],
                States.CONFIRM_OFFER: [
                    CallbackQueryHandler(confirm_offer, pattern=r'^confirm_offer$'),
                    CallbackQueryHandler(show_drug_buttons, pattern=r'^back_to_selection$')
           ],
                States.COMPENSATION_SELECTION: [
                    CallbackQueryHandler(show_two_column_selection, pattern=r'^add_more$'),
                    CallbackQueryHandler(handle_compensation_selection, pattern=r'^compensate$'),
                    CallbackQueryHandler(handle_compensation_selection, pattern=r'^comp_\d+$'),
                    CallbackQueryHandler(confirm_totals, pattern=r'^finish_selection$')
          ],
                States.COMPENSATION_QUANTITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_compensation_quantity),
                    CallbackQueryHandler(show_two_column_selection, pattern=r'^back_to_compensation$')
          ],
                States.CONFIRM_TOTALS: [
                    CallbackQueryHandler(show_two_column_selection, pattern=r'^edit_selection$'),
                    CallbackQueryHandler(confirm_totals, pattern=r'^back_to_totals$'),
                    CallbackQueryHandler(send_offer, pattern=r'^send_offer$')
                ]  
         },
         fallbacks=[CommandHandler('cancel', cancel)],
         allow_reentry=True,
         per_message=True  # To address the PTBUserWarning
        )
        
        # Add conversation handler for medical categories
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
            fallbacks=[CommandHandler('cancel', cancel)],
            allow_reentry=True
        )
        
        # Add conversation handler for admin commands
        admin_handler = ConversationHandler(
            entry_points=[
                CommandHandler('upload_excel', upload_excel_start),
                CommandHandler('generate_code', generate_simple_code),
                CommandHandler('verify', verify_pharmacy)
            ],
            states={
                States.ADMIN_UPLOAD_EXCEL: [
                    MessageHandler(filters.Document.ALL | (filters.TEXT & filters.Entity("url")), handle_excel_upload)
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            allow_reentry=True
        )
        
        # Add handlers
                # Add callback query handler for admin actions

        application.add_handler(registration_handler)
        application.add_handler(drug_handler)
        application.add_handler(needs_handler)
        application.add_handler(trade_handler)
        application.add_handler(categories_handler)
        application.add_handler(admin_handler)
        application.add_handler(InlineQueryHandler(handle_inline_query))
        application.add_handler(ChosenInlineResultHandler(handle_chosen_inline_result))
        
        # Add callback query handler
        application.add_handler(CallbackQueryHandler(approve_user, pattern="^approve_user_"))
        # In your main() function:
        application.add_handler(CallbackQueryHandler(confirm_offer, pattern="^confirm_offer$"))
        application.add_handler(CallbackQueryHandler(reject_user, pattern="^reject_user_"))
        # In your main() function where you set up handlers:
        application.add_handler(CallbackQueryHandler(submit_offer, pattern="^submit_offer$"))
        # Add this to your main() function where you set up handlers:
        application.add_handler(CallbackQueryHandler(select_drug, pattern="^select_target_"))
        application.add_handler(CallbackQueryHandler(select_drug, pattern="^select_mine_"))
        application.add_handler(CallbackQueryHandler(callback_handler))
        
        # Add error handler
        application.add_error_handler(error_handler)
        
        # Start the Bot
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.critical(f"Fatal error in main: {e}")
        raise

if __name__ == '__main__':
    main()
