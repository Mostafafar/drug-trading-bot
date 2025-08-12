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
    CONFIRM_DRUG_SELECTION = auto()
    ENTER_EXPIRY_DATE = auto()
    ENTER_QUANTITY = auto()
    CONFIRM_ADD_DRUG = auto()

# Initialize global drug list
drug_list = []

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
            
            # Personnel codes table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS personnel_codes (
                code TEXT PRIMARY KEY,
                creator_id BIGINT REFERENCES pharmacies(user_id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )''')
            
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

def validate_date(date_str: str) -> bool:
    """Validate date format (either Persian or Gregorian)"""
    persian_pattern = r'^\d{4}[/-]\d{2}[/-]\d{2}$'
    gregorian_pattern = r'^\d{4}[/-]\d{2}[/-]\d{2}$'
    return bool(re.match(persian_pattern, date_str) or bool(re.match(gregorian_pattern, date_str))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
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

async def add_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start process to add a drug item with inline query"""
    try:
        await ensure_user(update, context)
        
        keyboard = [
            [InlineKeyboardButton("🔍 جستجوی دارو", switch_inline_query_current_chat="")],
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

async def handle_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline query for drug search"""
    query = update.inline_query.query
    if not query:
        return
    
    results = []
    for idx, (name, price) in enumerate(drug_list):
        if query.lower() in name.lower():
            title_part = name.split()[0]
            desc_part = ' '.join(name.split()[1:]) if len(name.split()) > 1 else name
            
            results.append(
                InlineQueryResultArticle(
                    id=str(idx),
                    title=title_part,
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
        if len(results) >= 50:
            break
    
    await update.inline_query.answer(results)

async def handle_chosen_inline_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process selection from inline query"""
    try:
        idx = int(update.chosen_inline_result.result_id)
        selected_drug = drug_list[idx]
        
        context.user_data['selected_drug'] = {
            'name': selected_drug[0],
            'price': selected_drug[1]
        }
        
        keyboard = [
            [InlineKeyboardButton("✅ تأیید دارو", callback_data="confirm_drug")],
            [InlineKeyboardButton("🔙 جستجوی مجدد", callback_data="back_to_search")]
        ]
        
        await context.bot.send_message(
            chat_id=update.chosen_inline_result.from_user.id,
            text=f"🔍 داروی انتخاب شده:\n\n"
                 f"💊 نام: {selected_drug[0]}\n"
                 f"💰 قیمت: {selected_drug[1]}\n\n"
                 "آیا این دارو را تأیید می‌کنید؟",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.CONFIRM_DRUG_SELECTION
    except Exception as e:
        logger.error(f"Error processing drug selection: {e}")
        return ConversationHandler.END

async def ask_for_expiry_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask user for drug expiry date"""
    try:
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_drug_confirmation")]
        ]
        
        await query.edit_message_text(
            text="📅 لطفا تاریخ انقضا را به فرمت زیر وارد کنید:\n"
                 "مثال: 1405/12/15 یا 2026-03-20",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.ENTER_EXPIRY_DATE
    except Exception as e:
        logger.error(f"Error in ask_for_expiry_date: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def ask_for_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask user for drug quantity"""
    try:
        drug_date = update.message.text.strip()
        
        if not validate_date(drug_date):
            await update.message.reply_text(
                "⚠️ فرمت تاریخ نامعتبر است!\n"
                "لطفا تاریخ را به یکی از فرمت‌های زیر وارد کنید:\n"
                "1405/12/15 یا 2026-03-20"
            )
            return States.ENTER_EXPIRY_DATE
        
        context.user_data['drug_date'] = drug_date
        
        keyboard = [
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_date_entry")]
        ]
        
        await update.message.reply_text(
            f"✅ تاریخ انقضا ثبت شد: {drug_date}\n\n"
            "📦 لطفا تعداد یا مقدار موجود را وارد کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.ENTER_QUANTITY
    except Exception as e:
        logger.error(f"Error in ask_for_quantity: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def confirm_add_drug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm drug addition before saving"""
    try:
        quantity = update.message.text.strip()
        
        try:
            quantity = int(quantity)
            if quantity <= 0:
                await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید.")
                return States.ENTER_QUANTITY
        except ValueError:
            await update.message.reply_text("لطفا یک عدد صحیح وارد کنید.")
            return States.ENTER_QUANTITY
        
        context.user_data['quantity'] = quantity
        
        selected_drug = context.user_data['selected_drug']
        drug_date = context.user_data['drug_date']
        
        keyboard = [
            [InlineKeyboardButton("✅ تأیید و ذخیره", callback_data="final_confirm")],
            [InlineKeyboardButton("✏️ ویرایش تعداد", callback_data="edit_quantity")],
            [InlineKeyboardButton("✏️ ویرایش تاریخ", callback_data="edit_date")],
            [InlineKeyboardButton("✏️ تغییر دارو", callback_data="change_drug")]
        ]
        
        await update.message.reply_text(
            f"📋 اطلاعات نهایی دارو:\n\n"
            f"💊 نام: {selected_drug['name']}\n"
            f"💰 قیمت: {selected_drug['price']}\n"
            f"📅 تاریخ انقضا: {drug_date}\n"
            f"📦 تعداد: {quantity}\n\n"
            "آیا اطلاعات صحیح است؟",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.CONFIRM_ADD_DRUG
    except Exception as e:
        logger.error(f"Error in confirm_add_drug: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def save_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save drug to database"""
    try:
        query = update.callback_query
        await query.answer()
        
        selected_drug = context.user_data.get('selected_drug')
        drug_date = context.user_data.get('drug_date')
        quantity = context.user_data.get('quantity')
        
        if not all([selected_drug, drug_date, quantity]):
            await query.edit_message_text("اطلاعات ناقص است. لطفا دوباره تلاش کنید.")
            return ConversationHandler.END
            
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                INSERT INTO drug_items (user_id, name, price, date, quantity)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                ''', (
                    update.effective_user.id,
                    selected_drug['name'],
                    selected_drug['price'],
                    drug_date,
                    quantity
                ))
                drug_id = cursor.fetchone()[0]
                conn.commit()
                
                await query.edit_message_text(
                    f"✅ دارو با موفقیت اضافه شد!\n\n"
                    f"🆔 کد: {drug_id}\n"
                    f"💊 نام: {selected_drug['name']}\n"
                    f"💰 قیمت: {selected_drug['price']}\n"
                    f"📅 تاریخ انقضا: {drug_date}\n"
                    f"📦 تعداد: {quantity}"
                )
                
                # Clear context
                context.user_data.pop('selected_drug', None)
                context.user_data.pop('drug_date', None)
                context.user_data.pop('quantity', None)
                
        except Exception as e:
            logger.error(f"Error saving drug: {e}")
            await query.edit_message_text("خطا در ثبت دارو. لطفا دوباره تلاش کنید.")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
                
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in save_drug_item: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

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
    """Handle drug search"""
    try:
        search_term = update.message.text.strip().lower()
        context.user_data['search_term'] = search_term
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
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
            logger.error(f"Error in search: {e}")
            await update.message.reply_text("خطا در جستجوی داروها.")
            return States.SEARCH_DRUG
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in handle_search: {e}")
        await update.message.reply_text("خطایی رخ داد.")
        return ConversationHandler.END

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Central callback query handler"""
    try:
        query = update.callback_query
        await query.answer()
        
        if not query.data:
            logger.warning("Empty callback data received")
            return

        if query.data == "back":
            return await handle_back(update, context)
        elif query.data == "cancel":
            return await cancel(update, context)
        elif query.data.startswith("pharmacy_"):
            return await select_pharmacy(update, context)
        elif query.data == "confirm_drug":
            return await ask_for_expiry_date(update, context)
        elif query.data == "back_to_drug_confirmation":
            return await show_drug_confirmation(update, context)
        elif query.data == "back_to_date_entry":
            return await ask_for_expiry_date(update, context)
        elif query.data == "final_confirm":
            return await save_drug_item(update, context)
        elif query.data == "edit_quantity":
            return await ask_for_quantity(update, context)
        elif query.data == "edit_date":
            return await ask_for_expiry_date(update, context)
        elif query.data == "change_drug":
            return await add_drug_item(update, context)
        elif query.data == "back_to_search":
            return await add_drug_item(update, context)
        
        logger.warning(f"Unhandled callback data: {query.data}")
        await query.edit_message_text("این گزینه در حال حاضر قابل استفاده نیست.")
        
    except Exception as e:
        logger.error(f"Error processing callback {query.data}: {e}")
        try:
            await query.edit_message_text("خطایی در پردازش درخواست شما رخ داد.")
        except Exception as e:
            logger.error(f"Failed to edit message: {e}")

async def show_drug_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show drug confirmation after selection"""
    try:
        query = update.callback_query
        await query.answer()
        
        selected_drug = context.user_data.get('selected_drug')
        if not selected_drug:
            await query.edit_message_text("اطلاعات دارو یافت نشد. لطفا دوباره تلاش کنید.")
            return await add_drug_item(update, context)
        
        keyboard = [
            [InlineKeyboardButton("✅ تأیید دارو", callback_data="confirm_drug")],
            [InlineKeyboardButton("🔙 جستجوی مجدد", callback_data="back_to_search")]
        ]
        
        await query.edit_message_text(
            f"🔍 داروی انتخاب شده:\n\n"
            f"💊 نام: {selected_drug['name']}\n"
            f"💰 قیمت: {selected_drug['price']}\n\n"
            "آیا این دارو را تأیید می‌کنید؟",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.CONFIRM_DRUG_SELECTION
    except Exception as e:
        logger.error(f"Error in show_drug_confirmation: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

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
        application = ApplicationBuilder().token("8447101535:AAFMFkqJeMFNBfhzrY1VURkfJI-vu766LrY").build()
        
        # Add conversation handler for drug management
        drug_handler = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex('^اضافه کردن دارو$'), add_drug_item),
                CallbackQueryHandler(add_drug_item, pattern="^back_to_search$"),
                CallbackQueryHandler(show_drug_confirmation, pattern="^back_to_drug_confirmation$")
            ],
            states={
                States.SEARCH_DRUG_FOR_ADDING: [
                    InlineQueryHandler(handle_inline_query),
                    ChosenInlineResultHandler(handle_chosen_inline_result),
                    CallbackQueryHandler(add_drug_item, pattern="^back_to_search$")
                ],
                States.CONFIRM_DRUG_SELECTION: [
                    CallbackQueryHandler(ask_for_expiry_date, pattern="^confirm_drug$"),
                    CallbackQueryHandler(add_drug_item, pattern="^back_to_search$")
                ],
                States.ENTER_EXPIRY_DATE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, ask_for_quantity),
                    CallbackQueryHandler(show_drug_confirmation, pattern="^back_to_drug_confirmation$")
                ],
                States.ENTER_QUANTITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_add_drug),
                    CallbackQueryHandler(ask_for_expiry_date, pattern="^back_to_date_entry$")
                ],
                States.CONFIRM_ADD_DRUG: [
                    CallbackQueryHandler(save_drug_item, pattern="^final_confirm$"),
                    CallbackQueryHandler(ask_for_quantity, pattern="^edit_quantity$"),
                    CallbackQueryHandler(ask_for_expiry_date, pattern="^edit_date$"),
                    CallbackQueryHandler(add_drug_item, pattern="^change_drug$")
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            allow_reentry=True
        )
        
        # Add conversation handler for search
        search_handler = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex('^جستجوی دارو$'), search_drug)
            ],
            states={
                States.SEARCH_DRUG: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search)
                ],
                States.SELECT_PHARMACY: [
                    CallbackQueryHandler(select_pharmacy, pattern="^pharmacy_")
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            allow_reentry=True
        )
        
        # Add all handlers
        application.add_handler(CommandHandler('start', start))
        application.add_handler(drug_handler)
        application.add_handler(search_handler)
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
