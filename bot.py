import time
import re
import psycopg2
from psycopg2 import sql, extras
from telegram.ext import BaseHandler
from typing import Optional, Awaitable
from telegram.ext import BaseHandler, ContextTypes
from telegram import Update
import pandas as pd
import logging
import json
from telegram import (
    Update, 
    ReplyKeyboardMarkup, 
    ReplyKeyboardRemove, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackContext,
    CallbackQueryHandler,
    ContextTypes
)
from telegram.error import TimedOut
from enum import Enum, auto
import os
from pathlib import Path
import traceback
from difflib import SequenceMatcher
from datetime import datetime
import random
import requests
import openpyxl
from io import BytesIO
import asyncio

logger = logging.getLogger(__name__)

# Initialize paths and directories
current_dir = Path(__file__).parent
excel_file = current_dir / "DrugPrices.xlsx"
PHOTO_STORAGE = "registration_docs"

# Database configuration
DB_CONFIG = {
    'dbname': 'drug_trading',
    'user': 'postgres',
    'password': 'yourpassword',
    'host': 'localhost',
    'port': '5432'
}

# Ensure directories exist
Path(PHOTO_STORAGE).mkdir(exist_ok=True)

# ======== STATES ENUM ========
class States(Enum):
    # Registration states
    REGISTER_PHARMACY_NAME = auto()
    REGISTER_FOUNDER_NAME = auto()
    REGISTER_NATIONAL_CARD = auto()
    REGISTER_LICENSE = auto()
    REGISTER_MEDICAL_CARD = auto()
    REGISTER_PHONE = auto()
    REGISTER_ADDRESS = auto()
    REGISTER_LOCATION = auto()
    VERIFICATION_CODE = auto()
    ADMIN_VERIFICATION = auto()
    
    # Drug search and offer states
    SEARCH_DRUG = auto()
    SELECT_PHARMACY = auto()
    SELECT_ITEMS = auto()
    SELECT_QUANTITY = auto()
    CONFIRM_OFFER = auto()
    CONFIRM_TOTALS = auto()
    
    # Need addition states
    SELECT_NEED_CATEGORY = auto()
    ADD_NEED_NAME = auto()
    ADD_NEED_DESC = auto()
    ADD_NEED_QUANTITY = auto()
    SEARCH_DRUG_FOR_NEED = auto()
    SELECT_DRUG_FOR_NEED = auto()
    
    # Compensation states
    COMPENSATION_SELECTION = auto()
    COMPENSATION_QUANTITY = auto()
    
    # Drug addition states
    ADD_DRUG_DATE = auto()
    ADD_DRUG_QUANTITY = auto()
    SEARCH_DRUG_FOR_ADDING = auto()
    SELECT_DRUG_FOR_ADDING = auto()
    
    # Admin states
    ADMIN_UPLOAD_EXCEL = auto()
    EDIT_ITEM = auto()

# ======== END OF STATES ENUM ========

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    filename='bot.log',
    filemode='a'
)
logger = logging.getLogger(__name__)

# Verification codes storage
verification_codes = {}
admin_codes = {}  # Stores admin verification codes

# Admin chat ID - replace with your actual admin chat ID
ADMIN_CHAT_ID = 6680287530  # Example admin ID

# File download helper
async def download_file(file, file_type, user_id):
    """Download a file from Telegram and return the saved path"""
    file_name = f"{user_id}_{file_type}{os.path.splitext(file.file_path)[1]}"
    file_path = os.path.join(PHOTO_STORAGE, file_name)
    await file.download_to_drive(file_path)
    return file_path

def get_db_connection(max_retries: int = 3, retry_delay: float = 1.0):
    """Get a database connection with retry logic and validation"""
    conn = None
    last_error = None
    
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
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

def load_drug_data():
    """Load drug data from Excel file or GitHub"""
    global drug_list
    
    try:
        # First try to load from local file
        if excel_file.exists():
            df = pd.read_excel(excel_file, sheet_name="Sheet1")
            df = df.drop(columns=[col for col in df.columns if 'Unnamed' in col])
            drug_list = df[['name', 'price']].dropna().drop_duplicates().values.tolist()
            drug_list = [(str(name).strip(), str(price).strip()) for name, price in drug_list if str(name).strip()]
            logger.info(f"Successfully loaded {len(drug_list)} drugs from local Excel file")
            return True
        
        # If local file doesn't exist, try to load from GitHub
        github_url = "https://raw.githubusercontent.com/yourusername/yourrepo/main/DrugPrices.xlsx"
        response = requests.get(github_url)
        if response.status_code == 200:
            # Load the Excel file from GitHub
            excel_data = BytesIO(response.content)
            df = pd.read_excel(excel_data)
            df = df.drop(columns=[col for col in df.columns if 'Unnamed' in col])
            drug_list = df[['name', 'price']].dropna().drop_duplicates().values.tolist()
            drug_list = [(str(name).strip(), str(price).strip()) for name, price in drug_list if str(name).strip()]
            
            # Save locally for future use
            df.to_excel(excel_file, index=False)
            logger.info(f"Successfully loaded {len(drug_list)} drugs from GitHub and saved locally")
            return True
        
        logger.warning("Could not load drug data from either local file or GitHub")
        drug_list = []
        return False
        
    except Exception as e:
        logger.error(f"Error loading drug data: {e}")
        drug_list = []
        # Create backup if file exists but is corrupted
        if excel_file.exists():
            backup_file = current_dir / f"DrugPrices_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            excel_file.rename(backup_file)
            logger.info(f"Created backup of corrupted file at {backup_file}")
        return False

async def initialize_db():
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
                is_admin BOOLEAN DEFAULT FALSE
            )''')
            
            # Pharmacy info table
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
                location_lat DOUBLE PRECISION,
                location_lng DOUBLE PRECISION,
                admin_code TEXT UNIQUE,
                verified BOOLEAN DEFAULT FALSE,
                verified_at TIMESTAMP,
                admin_id BIGINT REFERENCES users(id)
            ''')
            
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
            
            # User categories (many-to-many)
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
            
            # Auto-match notifications table
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
            
            # Insert default medical categories
            default_categories = ['اعصاب', 'قلب', 'ارتوپد', 'زنان', 'گوارش', 'پوست', 'اطفال']
            for category in default_categories:
                cursor.execute('''
                INSERT INTO medical_categories (name)
                VALUES (%s)
                ON CONFLICT (name) DO NOTHING
                ''', (category,))
            
            # Create admin user if not exists
            cursor.execute('''
            INSERT INTO users (id, is_admin, is_verified)
            VALUES (%s, TRUE, TRUE)
            ON CONFLICT (id) DO UPDATE SET is_admin = TRUE
            ''', (ADMIN_CHAT_ID,))
            
            conn.commit()
    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

asyncio.get_event_loop().run_until_complete(initialize_db())
load_drug_data()

class UserApprovalMiddleware(BaseHandler):
    def __init__(self):
        super().__init__(self.check_update)
        
    async def check_update(self, update: object) -> Optional[Awaitable]:
        if not isinstance(update, Update):
            return True
            
        if update.message and update.message.text in ['/start', '/register', '/verify', '/admin_verify']:
            return True
        
        if (update.message and update.message.text and 
            (update.message.text.startswith('/approve') or update.message.text.startswith('/reject'))):
            return True
        
        if update.effective_user.id == ADMIN_CHAT_ID:
            return True
            
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                SELECT 1 FROM pharmacies 
                WHERE user_id = %s AND verified = TRUE
                ''', (update.effective_user.id,))
                if not cursor.fetchone():
                    await update.message.reply_text(
                        "⚠️ شما مجوز استفاده از ربات را ندارید.\n\n"
                        "لطفا ابتدا ثبت نام کنید و منتظر تایید مدیریت بمانید.\n"
                        "برای ثبت نام /register را ارسال کنید."
                    )
                    return False
                return True
        except Exception as e:
            logger.error(f"Error in approval check: {e}")
            return False
        finally:
            if conn:
                conn.close()

async def ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('''
            INSERT INTO users (id, first_name, last_name, username)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET 
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                username = EXCLUDED.username,
                last_active = CURRENT_TIMESTAMP
            ''', (user.id, user.first_name, user.last_name, user.username))
            conn.commit()
    except psycopg2.Error as e:
        logger.error(f"Error ensuring user: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def parse_price(price_str):
    if not price_str:
        return 0
    try:
        return float(str(price_str).replace(',', ''))
    except ValueError:
        return 0

def similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

async def check_for_matches(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Check if there are any matches between user's needs and available drugs"""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
            
            # Get user's needs
            cursor.execute('''
            SELECT id, name, quantity 
            FROM user_needs 
            WHERE user_id = %s
            ''', (user_id,))
            needs = cursor.fetchall()
            
            if not needs:
                return
            
            # Get all available drugs from pharmacies
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
                    if sim_score >= 0.7:  # Threshold for match
                        matches.append({
                            'need': dict(need),
                            'drug': dict(drug),
                            'similarity': sim_score
                        })
            
            if not matches:
                return
            
            # Send notifications and record in database
            for match in matches:
                try:
                    # Create notification message
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
                    
                    # Send notification
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        reply_markup=reply_markup
                    )
                    
                    # Record notification in database
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
                    logger.error(f"Failed to notify pharmacy: {e}")
                    if conn:
                        conn.rollback()
                        
    except Exception as e:
        logger.error(f"Error in check_for_matches: {e}")
    finally:
        if conn:
            conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, context)
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('''
            SELECT 1 FROM pharmacies 
            WHERE user_id = %s AND verified = TRUE
            ''', (update.effective_user.id,))
            if not cursor.fetchone():
                keyboard = [
                    [InlineKeyboardButton("ثبت نام با کد ادمین", callback_data="admin_verify")],
                    [InlineKeyboardButton("ثبت نام با مدارک", callback_data="register")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    "برای استفاده از ربات باید ثبت نام کنید. لطفا روش ثبت نام را انتخاب کنید:",
                    reply_markup=reply_markup
                )
                return
    except Exception as e:
        logger.error(f"Error checking pharmacy status: {e}")
    finally:
        if conn:
            conn.close()
    
    # Check for matches in background
    context.application.create_task(check_for_matches(update.effective_user.id, context))
    
    keyboard = [
        ['اضافه کردن دارو', 'جستجوی دارو'],
        ['تنظیم شاخه‌های دارویی', 'لیست داروهای من'],
        ['ثبت نیاز جدید', 'لیست نیازهای من']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(
        "به ربات تبادل دارو خوش آمدید! لطفا یک گزینه را انتخاب کنید:",
        reply_markup=reply_markup
    )

async def admin_verify_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "لطفا کد تایید داروخانه را وارد کنید:",
        reply_markup=ReplyKeyboardRemove()
    )
    return States.ADMIN_VERIFICATION

async def admin_verify_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_code = update.message.text.strip()
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('''
            SELECT user_id FROM pharmacies 
            WHERE admin_code = %s AND verified = TRUE
            ''', (user_code,))
            result = cursor.fetchone()
            
            if result:
                pharmacy_id = result[0]
                
                # Check if user already has a pharmacy
                cursor.execute('''
                SELECT 1 FROM pharmacies WHERE user_id = %s
                ''', (update.effective_user.id,))
                if cursor.fetchone():
                    await update.message.reply_text(
                        "شما قبلاً با یک داروخانه ثبت نام کرده‌اید."
                    )
                    return ConversationHandler.END
                
                # Add user to pharmacy
                cursor.execute('''
                INSERT INTO users (id, first_name, last_name, username, is_verified)
                VALUES (%s, %s, %s, %s, TRUE)
                ON CONFLICT (id) DO UPDATE SET
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    username = EXCLUDED.username,
                    is_verified = TRUE
                ''', (
                    update.effective_user.id,
                    update.effective_user.first_name,
                    update.effective_user.last_name,
                    update.effective_user.username
                ))
                
                await update.message.reply_text(
                    "✅ حساب شما با موفقیت تایید شد!\n\n"
                    "شما می‌توانید دارو به لیست اضافه کنید و نیازها را ثبت نمایید."
                )
                
                return await start(update, context)
            else:
                await update.message.reply_text("کد تایید نامعتبر است. لطفا دوباره تلاش کنید.")
                return States.ADMIN_VERIFICATION
                
    except Exception as e:
        logger.error(f"Error in admin verification: {e}")
        await update.message.reply_text("خطا در تایید حساب. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

async def upload_excel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def handle_excel_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.document:
        # Handle document upload
        file = await context.bot.get_file(update.message.document.file_id)
        file_path = await download_file(file, "drug_prices", "admin")
        
        try:
            # Try to read the Excel file
            df = pd.read_excel(file_path)
            df = df.drop(columns=[col for col in df.columns if 'Unnamed' in col])
            drug_list = df[['name', 'price']].dropna().drop_duplicates().values.tolist()
            drug_list = [(str(name).strip(), str(price).strip()) for name, price in drug_list if str(name).strip()]
            
            # Save to local file
            df.to_excel(excel_file, index=False)
            
            await update.message.reply_text(
                f"✅ فایل اکسل با موفقیت آپلود شد!\n\n"
                f"تعداد داروهای بارگذاری شده: {len(drug_list)}\n"
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
                "❌ خطا در پردازش فایل اکسل. لطفا مطمئن شوید فرمت فایل صحیح است."
            )
            
    elif update.message.text and update.message.text.startswith('http'):
        # Handle GitHub URL
        github_url = update.message.text.strip()
        
        try:
            response = requests.get(github_url)
            if response.status_code == 200:
                # Load the Excel file from GitHub
                excel_data = BytesIO(response.content)
                df = pd.read_excel(excel_data)
                df = df.drop(columns=[col for col in df.columns if 'Unnamed' in col])
                drug_list = df[['name', 'price']].dropna().drop_duplicates().values.tolist()
                drug_list = [(str(name).strip(), str(price).strip()) for name, price in drug_list if str(name).strip()]
                
                # Save locally
                df.to_excel(excel_file, index=False)
                
                await update.message.reply_text(
                    f"✅ فایل اکسل از گیتهاب با موفقیت بارگذاری شد!\n\n"
                    f"تعداد داروهای بارگذاری شده: {len(drug_list)}\n"
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
                        ''', (github_url,))
                        conn.commit()
                except Exception as e:
                    logger.error(f"Error saving excel info: {e}")
                finally:
                    if conn:
                        conn.close()
            else:
                await update.message.reply_text(
                    "❌ خطا در دریافت فایل از گیتهاب. لطفا از صحت لینک اطمینان حاصل کنید."
                )
                
        except Exception as e:
            logger.error(f"Error processing github excel: {e}")
            await update.message.reply_text(
                "❌ خطا در پردازش فایل اکسل از گیتهاب. لطفا مطمئن شوید لینک صحیح است."
            )
    else:
        await update.message.reply_text(
            "لطفا فایل اکسل یا لینک گیتهاب را ارسال کنید."
        )
        return States.ADMIN_UPLOAD_EXCEL
    
    return ConversationHandler.END

async def search_drug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, context)
    await update.message.reply_text("لطفا نام دارویی که می‌خواهید جستجو کنید را وارد کنید:")
    return States.SEARCH_DRUG

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        await update.message.reply_text("لطفا یک متن برای جستجو وارد کنید.")
        return States.SEARCH_DRUG
    
    search_term = update.message.text.strip()
    context.user_data['search_term'] = search_term

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
            
            # Get all matching drugs from database (with highest price for each name)
            cursor.execute('''
            SELECT 
                di.id, 
                di.user_id,
                di.name,
                MAX(di.price) as price,
                di.date,
                SUM(di.quantity) as quantity,
                p.name AS pharmacy_name
            FROM drug_items di
            JOIN pharmacies p ON di.user_id = p.user_id
            WHERE di.name ILIKE %s AND di.quantity > 0
            GROUP BY di.id, di.user_id, di.name, di.date, p.name
            ORDER BY di.price DESC
            ''', (f'%{search_term}%',))
            results = cursor.fetchall()

            if results:
                context.user_data['search_results'] = [dict(row) for row in results]
                
                message = "نتایج جستجو (نمایش بالاترین قیمت برای هر دارو):\n\n"
                for idx, item in enumerate(results[:5]):
                    message += (
                        f"{idx+1}. {item['name']} - قیمت: {item['price'] or 'نامشخص'}\n"
                        f"   داروخانه: {item['pharmacy_name']}\n"
                        f"   موجودی: {item['quantity']}\n\n"
                    )
                
                if len(results) > 5:
                    message += f"➕ {len(results)-5} نتیجه دیگر...\n\n"
                
                pharmacies = {}
                for item in results:
                    pharmacy_id = item['user_id']
                    if pharmacy_id not in pharmacies:
                        pharmacies[pharmacy_id] = {
                            'name': item['pharmacy_name'],
                            'count': 0,
                            'items': []
                        }
                    pharmacies[pharmacy_id]['count'] += 1
                    pharmacies[pharmacy_id]['items'].append(dict(item))
                
                context.user_data['pharmacies'] = pharmacies
                
                keyboard = []
                for pharmacy_id, pharmacy_data in pharmacies.items():
                    keyboard.append([InlineKeyboardButton(
                        f"داروخانه: {pharmacy_data['name']} ({pharmacy_data['count']} آیتم)", 
                        callback_data=f"pharmacy_{pharmacy_id}"
                    )])
                
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    message + "لطفا داروخانه مورد نظر را انتخاب کنید:",
                    reply_markup=reply_markup
                )
                return States.SELECT_PHARMACY
            else:
                await update.message.reply_text("هیچ دارویی با این نام یافت نشد.")
                return ConversationHandler.END
    except psycopg2.Error as e:
        logger.error(f"Database error in search: {e}")
        await update.message.reply_text("خطایی در پایگاه داده رخ داده است.")
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

async def select_pharmacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "back":
        await query.edit_message_text("لطفا نام دارویی که می‌خواهید جستجو کنید را وارد کنید:")
        return States.SEARCH_DRUG

    if query.data.startswith("pharmacy_"):
        pharmacy_id = int(query.data.split("_")[1])
        pharmacies = context.user_data.get('pharmacies', {})
        pharmacy_data = pharmacies.get(pharmacy_id)
        
        if pharmacy_data:
            context.user_data['selected_pharmacy'] = {
                'id': pharmacy_id,
                'name': pharmacy_data['name']
            }
            context.user_data['pharmacy_drugs'] = pharmacy_data['items']
            context.user_data['selected_items'] = []
            
            # Get buyer's (current user) drugs
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                    cursor.execute('''
                    SELECT id, name, price, quantity 
                    FROM drug_items 
                    WHERE user_id = %s AND quantity > 0
                    ''', (update.effective_user.id,))
                    buyer_drugs = cursor.fetchall()
                    context.user_data['buyer_drugs'] = [dict(row) for row in buyer_drugs]
                    
                    # Get pharmacy's medical categories
                    cursor.execute('''
                    SELECT mc.id, mc.name 
                    FROM user_categories uc
                    JOIN medical_categories mc ON uc.category_id = mc.id
                    WHERE uc.user_id = %s
                    ''', (pharmacy_id,))
                    pharmacy_categories = cursor.fetchall()
                    context.user_data['pharmacy_categories'] = [dict(row) for row in pharmacy_categories]
                    
            except Exception as e:
                logger.error(f"Error fetching data: {e}")
                context.user_data['buyer_drugs'] = []
                context.user_data['pharmacy_categories'] = []
            finally:
                if conn:
                    conn.close()
            
            return await show_two_column_selection(update, context)

async def show_two_column_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show the drug selection interface with proper v20+ syntax"""
    pharmacy = context.user_data.get('selected_pharmacy', {})
    pharmacy_drugs = context.user_data.get('pharmacy_drugs', [])
    buyer_drugs = context.user_data.get('buyer_drugs', [])
    selected_items = context.user_data.get('selected_items', [])
    
    # Create keyboard
    keyboard = []
    max_length = max(len(pharmacy_drugs), len(buyer_drugs))
    
    for i in range(max_length):
        row = []
        # Pharmacy drugs column
        if i < len(pharmacy_drugs):
            drug = pharmacy_drugs[i]
            is_selected = any(
                item['id'] == drug['id'] and item.get('type') == 'pharmacy_drug'
                for item in selected_items
            )
            emoji = "✅ " if is_selected else ""
            row.append(InlineKeyboardButton(
                f"{emoji}💊 {drug['name'][:15]}", 
                callback_data=f"pharmacydrug_{drug['id']}"
            ))
        else:
            row.append(InlineKeyboardButton(" ", callback_data="none"))
        
        # Buyer drugs column
        if i < len(buyer_drugs):
            drug = buyer_drugs[i]
            is_selected = any(
                item['id'] == drug['id'] and item.get('type') == 'buyer_drug'
                for item in selected_items
            )
            emoji = "✅ " if is_selected else ""
            row.append(InlineKeyboardButton(
                f"{emoji}📝 {drug['name'][:15]}", 
                callback_data=f"buyerdrug_{drug['id']}"
            ))
        else:
            row.append(InlineKeyboardButton(" ", callback_data="none"))
        
        keyboard.append(row)

    # Add control buttons
    keyboard.append([
        InlineKeyboardButton("💰 محاسبه جمع", callback_data="finish_selection"),
        InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_pharmacies"),
        InlineKeyboardButton("❌ لغو", callback_data="cancel")
    ])

    # Create message text
    message = (
        f"🔹 داروخانه: {pharmacy.get('name', '')}\n\n"
        "💊 داروهای داروخانه | 📝 داروهای شما برای تبادل\n\n"
        "علامت ✅ نشان‌دهنده انتخاب است\n"
        "پس از انتخاب موارد، روی «محاسبه جمع» کلیک کنید"
    )

    # Send or update message
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard))
    
    return States.SELECT_ITEMS

async def select_items(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle item selection with proper v20+ typing"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await cancel(update, context)
        return ConversationHandler.END

    if query.data == "back_to_pharmacies":
        # Go back to pharmacy selection
        search_term = context.user_data.get('search_term', '')
        message = f"نتایج جستجو برای '{search_term}':\n\n"
        
        pharmacies = context.user_data.get('pharmacies', {})
        keyboard = []
        for pharmacy_id, pharmacy_data in pharmacies.items():
            keyboard.append([InlineKeyboardButton(
                f"داروخانه: {pharmacy_data['name']} ({pharmacy_data['count']} آیتم)", 
                callback_data=f"pharmacy_{pharmacy_id}"
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back")])
        
        await query.edit_message_text(
            message + "لطفا داروخانه مورد نظر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard))
        return States.SELECT_PHARMACY

    if query.data == "finish_selection":
        selected_items = context.user_data.get('selected_items', [])
        if not selected_items:
            await query.answer("لطفا حداقل یک مورد را انتخاب کنید", show_alert=True)
            return States.SELECT_ITEMS
        
        # Calculate totals
        pharmacy_total = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in selected_items if item.get('type') == 'pharmacy_drug'
        )
        
        buyer_total = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in selected_items if item.get('type') == 'buyer_drug'
        )
        
        difference = pharmacy_total - buyer_total
        
        message = (
            "📊 جمع کل انتخاب‌ها:\n\n"
            f"💊 جمع داروهای داروخانه: {pharmacy_total:,}\n"
            f"📝 جمع داروهای شما: {buyer_total:,}\n"
            f"💰 تفاوت: {abs(difference):,} ({'به نفع شما' if difference < 0 else 'به نفع داروخانه'})\n\n"
        )
        
        if difference != 0:
            message += "برای جبران تفاوت می‌توانید از دکمه زیر استفاده کنید:\n"
            keyboard = [
                [InlineKeyboardButton("➕ جبران تفاوت", callback_data="compensate")],
                [InlineKeyboardButton("✅ تایید نهایی", callback_data="confirm_totals")],
                [InlineKeyboardButton("✏️ ویرایش", callback_data="edit_selection")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_items")]
            ]
        else:
            message += "آیا مایل به ادامه هستید؟"
            keyboard = [
                [InlineKeyboardButton("✅ تایید نهایی", callback_data="confirm_totals")],
                [InlineKeyboardButton("✏️ ویرایش", callback_data="edit_selection")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_items")]
            ]
        
        await query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.CONFIRM_TOTALS

    elif query.data == "compensate":
        difference = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in context.user_data['selected_items'] 
            if item.get('type') == 'pharmacy_drug'
        ) - sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in context.user_data['selected_items'] 
            if item.get('type') == 'buyer_drug'
        )
        
        if difference > 0:  # Pharmacy has more value, buyer needs to compensate
            selected_drug_ids = [
                item['id'] for item in context.user_data['selected_items'] 
                if item.get('type') == 'buyer_drug'
            ]
            
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                    cursor.execute('''
                    SELECT id, name, price, quantity 
                    FROM drug_items 
                    WHERE user_id = %s AND quantity > 0 AND id NOT IN %s
                    ''', (update.effective_user.id, tuple(selected_drug_ids) if selected_drug_ids else (None,)))
                    
                    remaining_drugs = cursor.fetchall()
                    
                    if not remaining_drugs:
                        await query.answer("داروی دیگری برای جبران ندارید!", show_alert=True)
                        return States.SELECT_ITEMS
                    
                    context.user_data['compensation'] = {
                        'difference': difference,
                        'remaining_diff': difference,
                        'selected_items': [],
                        'compensating_user': 'buyer'
                    }
                    
                    keyboard = []
                    for drug in remaining_drugs:
                        keyboard.append([InlineKeyboardButton(
                            f"{drug['name']} ({drug['price']}) - موجودی: {drug['quantity']}", 
                            callback_data=f"comp_{drug['id']}"
                        )])
                    
                    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_totals")])
                    
                    await query.edit_message_text(
                        text=f"🔻 نیاز به جبران: {difference:,}\n\n"
                             f"لطفا از داروهای خود برای جبران تفاوت انتخاب کنید:",
                        reply_markup=InlineKeyboardMarkup(keyboard))
                    return States.COMPENSATION_SELECTION
                    
            except Exception as e:
                logger.error(f"Error getting remaining drugs: {e}")
                await query.edit_message_text("خطا در دریافت داروها")
                return States.SELECT_ITEMS
            finally:
                if conn:
                    conn.close()
                
        else:  # Buyer has more value, pharmacy needs to compensate
            selected_drug_ids = [
                item['id'] for item in context.user_data['selected_items'] 
                if item.get('type') == 'pharmacy_drug'
            ]
            
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                    cursor.execute('''
                    SELECT id, name, price, quantity 
                    FROM drug_items 
                    WHERE user_id = %s AND quantity > 0 AND id NOT IN %s
                    ''', (context.user_data['selected_pharmacy']['id'], tuple(selected_drug_ids) if selected_drug_ids else (None,)))
                    
                    remaining_drugs = cursor.fetchall()
                    
                    if not remaining_drugs:
                        await query.answer("داروخانه داروی دیگری برای جبران ندارد!", show_alert=True)
                        return States.SELECT_ITEMS
                    
                    context.user_data['compensation'] = {
                        'difference': abs(difference),
                        'remaining_diff': abs(difference),
                        'selected_items': [],
                        'compensating_user': 'pharmacy'
                    }
                    
                    keyboard = []
                    for drug in remaining_drugs:
                        keyboard.append([InlineKeyboardButton(
                            f"{drug['name']} ({drug['price']}) - موجودی: {drug['quantity']}", 
                            callback_data=f"comp_{drug['id']}"
                        )])
                    
                    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_totals")])
                    
                    await query.edit_message_text(
                        text=f"🔻 نیاز به جبران: {abs(difference):,}\n\n"
                             f"لطفا از داروهای داروخانه برای جبران تفاوت انتخاب کنید:",
                        reply_markup=InlineKeyboardMarkup(keyboard))
                    return States.COMPENSATION_SELECTION
                    
            except Exception as e:
                logger.error(f"Error getting remaining drugs: {e}")
                await query.edit_message_text("خطا در دریافت داروها")
                return States.SELECT_ITEMS
            finally:
                if conn:
                    conn.close()

    elif query.data == "back_to_items":
        return await show_two_column_selection(update, context)
        
    elif query.data == "back_to_totals":
        # Recalculate totals
        selected_items = context.user_data.get('selected_items', [])
        pharmacy_total = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in selected_items if item.get('type') == 'pharmacy_drug'
        )
        
        buyer_total = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in selected_items if item.get('type') == 'buyer_drug'
        )
        
        difference = pharmacy_total - buyer_total
        
        message = (
            "📊 جمع کل انتخاب‌ها:\n\n"
            f"💊 جمع داروهای داروخانه: {pharmacy_total:,}\n"
            f"📝 جمع داروهای شما: {buyer_total:,}\n"
            f"💰 تفاوت: {abs(difference):,} ({'به نفع شما' if difference < 0 else 'به نفع داروخانه'})\n\n"
        )
        
        if difference != 0:
            message += "برای جبران تفاوت می‌توانید از دکمه زیر استفاده کنید:\n"
            keyboard = [
                [InlineKeyboardButton("➕ جبران تفاوت", callback_data="compensate")],
                [InlineKeyboardButton("✅ تایید نهایی", callback_data="confirm_totals")],
                [InlineKeyboardButton("✏️ ویرایش", callback_data="edit_selection")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_items")]
            ]
        else:
            message += "آیا مایل به ادامه هستید؟"
            keyboard = [
                [InlineKeyboardButton("✅ تایید نهایی", callback_data="confirm_totals")],
                [InlineKeyboardButton("✏️ ویرایش", callback_data="edit_selection")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_items")]
            ]
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard))
        return States.CONFIRM_TOTALS

    # Handle drug selection/deselection
    elif query.data.startswith(("pharmacydrug_", "buyerdrug_")):
        item_type, item_id = query.data.split("_")
        item_id = int(item_id)
        
        selected_items = context.user_data.get('selected_items', [])
        
        # Toggle selection
        existing_idx = next(
            (i for i, item in enumerate(selected_items) 
             if item.get('id') == item_id and 
             ((item_type == "pharmacydrug" and item.get('type') == 'pharmacy_drug') or
              (item_type == "buyerdrug" and item.get('type') == 'buyer_drug'))
            ), None)
        
        if existing_idx is not None:
            selected_items.pop(existing_idx)
        else:
            # Find the item in available items
            if item_type == "pharmacydrug":
                source = context.user_data.get('pharmacy_drugs', [])
                item_type = 'pharmacy_drug'
            else:
                source = context.user_data.get('buyer_drugs', [])
                item_type = 'buyer_drug'
            
            item = next((i for i in source if i['id'] == item_id), None)
            if item:
                item_copy = item.copy()
                item_copy['type'] = item_type
                selected_items.append(item_copy)
        
        context.user_data['selected_items'] = selected_items
    
    return await show_two_column_selection(update, context)

async def handle_compensation_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "comp_finish":
        comp_data = context.user_data.get('compensation', {})
        if not comp_data.get('selected_items'):
            await query.answer("لطفا حداقل یک مورد را انتخاب کنید", show_alert=True)
            return
        
        # Add compensation items to selected items
        selected_items = context.user_data.get('selected_items', [])
        for item in comp_data['selected_items']:
            item_copy = item.copy()
            item_copy['type'] = f"{comp_data['compensating_user']}_comp"
            selected_items.append(item_copy)
        
        context.user_data['selected_items'] = selected_items
        
        # Recalculate totals
        pharmacy_total = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in selected_items 
            if item.get('type') in ('pharmacy_drug', 'pharmacy_comp')
        )
        
        buyer_total = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in selected_items 
            if item.get('type') in ('buyer_drug', 'buyer_comp')
        )
        
        difference = pharmacy_total - buyer_total
        
        message = (
            "📊 جمع کل پس از جبران:\n\n"
            f"💊 جمع داروهای داروخانه: {pharmacy_total:,}\n"
            f"📝 جمع داروهای شما: {buyer_total:,}\n"
            f"💰 تفاوت نهایی: {abs(difference):,} ({'به نفع شما' if difference < 0 else 'به نفع داروخانه'})\n\n"
            "آیا مایل به ادامه هستید؟"
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ تایید نهایی", callback_data="confirm_totals")],
            [InlineKeyboardButton("✏️ ویرایش", callback_data="edit_selection")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_items")]
        ]
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard))
        return States.CONFIRM_TOTALS
    
    elif query.data == "back_to_totals":
        # Recalculate totals
        selected_items = context.user_data.get('selected_items', [])
        pharmacy_total = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in selected_items if item.get('type') == 'pharmacy_drug'
        )
        
        buyer_total = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in selected_items if item.get('type') == 'buyer_drug'
        )
        
        difference = pharmacy_total - buyer_total
        
        message = (
            "📊 جمع کل انتخاب‌ها:\n\n"
            f"💊 جمع داروهای داروخانه: {pharmacy_total:,}\n"
            f"📝 جمع داروهای شما: {buyer_total:,}\n"
            f"💰 تفاوت: {abs(difference):,} ({'به نفع شما' if difference < 0 else 'به نفع داروخانه'})\n\n"
        )
        
        if difference != 0:
            message += "برای جبران تفاوت می‌توانید از دکمه زیر استفاده کنید:\n"
            keyboard = [
                [InlineKeyboardButton("➕ جبران تفاوت", callback_data="compensate")],
                [InlineKeyboardButton("✅ تایید نهایی", callback_data="confirm_totals")],
                [InlineKeyboardButton("✏️ ویرایش", callback_data="edit_selection")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_items")]
            ]
        else:
            message += "آیا مایل به ادامه هستید؟"
            keyboard = [
                [InlineKeyboardButton("✅ تایید نهایی", callback_data="confirm_totals")],
                [InlineKeyboardButton("✏️ ویرایش", callback_data="edit_selection")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_items")]
            ]
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard))
        return States.CONFIRM_TOTALS
    
    elif query.data.startswith("comp_"):  # Item selected
        item_id = int(query.data.split("_")[1])
        
        # Get item details
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT id, name, price, quantity 
                FROM drug_items 
                WHERE id = %s
                ''', (item_id,))
                item = cursor.fetchone()
                
                if not item:
                    await query.answer("آیتم یافت نشد.")
                    return
                
                context.user_data['current_comp_item'] = dict(item)
                
                await query.edit_message_text(
                    f"لطفا تعداد را برای جبران با {item['name']} وارد کنید:\n\n"
                    f"قیمت واحد: {item['price']}\n"
                    f"حداکثر موجودی: {item['quantity']}\n"
                    f"تفاوت باقیمانده: {context.user_data['compensation']['remaining_diff']:,}"
                )
                return States.COMPENSATION_QUANTITY
                
        except Exception as e:
            logger.error(f"Error getting item details: {e}")
            await query.edit_message_text("خطا در دریافت اطلاعات آیتم.")
        finally:
            if conn:
                conn.close()

async def handle_compensation_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        quantity = int(update.message.text)
        current_item = context.user_data.get('current_comp_item', {})
        comp_data = context.user_data.get('compensation', {})
        
        if quantity <= 0 or quantity > current_item.get('quantity', 0):
            await update.message.reply_text(
                f"لطفا عددی بین 1 و {current_item.get('quantity', 0)} وارد کنید."
            )
            return States.COMPENSATION_QUANTITY
        
        # Calculate compensation value
        comp_value = parse_price(current_item['price']) * quantity
        
        # Add to selected items
        comp_data['selected_items'].append({
            'id': current_item['id'],
            'name': current_item['name'],
            'price': current_item['price'],
            'selected_quantity': quantity,
            'comp_value': comp_value
        })
        
        # Update remaining difference
        comp_data['remaining_diff'] = max(0, comp_data['difference'] - sum(
            item['comp_value'] for item in comp_data['selected_items']
        ))
        
        # Show updated status
        selected_text = "\n".join(
            f"{item['name']} x{item['selected_quantity']} = {item['comp_value']:,}" 
            for item in comp_data['selected_items']
        )
        
        await update.message.reply_text(
            f"✅ آیتم اضافه شد:\n\n{selected_text}\n\n"
            f"💰 جمع جبران فعلی: {sum(item['comp_value'] for item in comp_data['selected_items']):,}\n"
            f"🔹 باقیمانده تفاوت: {comp_data['remaining_diff']:,}\n\n"
            "می‌توانید اقلام بیشتری انتخاب کنید یا «اتمام انتخاب» را بزنید."
        )
        
        # Show remaining items if needed
        if comp_data['remaining_diff'] > 0:
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                    
                    if comp_data.get('compensating_user') == 'buyer':
                        cursor.execute('''
                        SELECT id, name, price, quantity 
                        FROM drug_items 
                        WHERE user_id = %s AND quantity > 0 AND id NOT IN %s
                        ''', (
                            update.effective_user.id, 
                            tuple(i['id'] for i in comp_data['selected_items']) if comp_data['selected_items'] else (None,)
                        ))
                    else:
                        cursor.execute('''
                        SELECT id, name, price, quantity 
                        FROM drug_items 
                        WHERE user_id = %s AND quantity > 0 AND id NOT IN %s
                        ''', (
                            context.user_data['selected_pharmacy']['id'], 
                            tuple(i['id'] for i in comp_data['selected_items']) if comp_data['selected_items'] else (None,)
                        ))
                        
                    remaining_drugs = cursor.fetchall()
                    
                    if remaining_drugs:
                        keyboard = []
                        for drug in remaining_drugs:
                            keyboard.append([InlineKeyboardButton(
                                f"{drug['name']} ({drug['price']}) - موجودی: {drug['quantity']}", 
                                callback_data=f"comp_{drug['id']}"
                            )])
                        keyboard.append([InlineKeyboardButton("اتمام انتخاب", callback_data="comp_finish")])
                        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_totals")])
                        
                        await update.message.reply_text(
                            "لطفا آیتم دیگری برای جبران انتخاب کنید:",
                            reply_markup=InlineKeyboardMarkup(keyboard))
                        return States.COMPENSATION_SELECTION
            
            except Exception as e:
                logger.error(f"Error showing remaining items: {e}")
            finally:
                if conn:
                    conn.close()
        
        # If difference is covered or no more items
        keyboard = [
            [InlineKeyboardButton("اتمام انتخاب", callback_data="comp_finish")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_totals")]
        ]
        await update.message.reply_text(
            "برای نهایی کردن انتخاب کلیک کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard))
        return States.COMPENSATION_SELECTION
        
    except ValueError:
        await update.message.reply_text("لطفا یک عدد صحیح وارد کنید.")
        return States.COMPENSATION_QUANTITY

async def confirm_totals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_totals":
        selected_items = context.user_data.get('selected_items', [])
        pharmacy = context.user_data.get('selected_pharmacy', {})
        buyer = update.effective_user
        
        if not selected_items or not pharmacy:
            await query.edit_message_text("خطا در اطلاعات پیشنهاد. لطفا دوباره تلاش کنید.")
            return ConversationHandler.END
        
        conn = None
        try:
            # Calculate totals
            pharmacy_total = sum(
                parse_price(item['price']) * item.get('selected_quantity', 1)
                for item in selected_items 
                if item.get('type') in ('pharmacy_drug', 'pharmacy_comp')
            )
            
            buyer_total = sum(
                parse_price(item['price']) * item.get('selected_quantity', 1)
                for item in selected_items 
                if item.get('type') in ('buyer_drug', 'buyer_comp')
            )
            
            difference = pharmacy_total - buyer_total
            
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Insert offer
                cursor.execute('''
                INSERT INTO offers (pharmacy_id, buyer_id, status, total_price)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                ''', (
                    pharmacy['id'],
                    buyer.id,
                    'pending',
                    pharmacy_total
                ))
                offer_id = cursor.fetchone()[0]
                
                # Insert offer items
                for item in selected_items:
                    if item['type'] in ('pharmacy_drug', 'buyer_drug'):
                        cursor.execute('''
                        INSERT INTO offer_items (
                            offer_id, drug_name, price, quantity, item_type
                        ) VALUES (%s, %s, %s, %s, %s)
                        ''', (
                            offer_id,
                            item['name'],
                            item['price'],
                            item.get('selected_quantity', 1),
                            'pharmacy_drug' if item['type'] == 'pharmacy_drug' else 'buyer_drug'
                        ))
                    elif item['type'] in ('pharmacy_comp', 'buyer_comp'):
                        cursor.execute('''
                        INSERT INTO compensation_items (
                            offer_id, drug_id, quantity
                        ) VALUES (%s, %s, %s)
                        ''', (
                            offer_id,
                            item['id'],
                            item['selected_quantity']
                        ))
                
                conn.commit()
                
                # Prepare notification message for pharmacy
                offer_message = f"📬 پیشنهاد جدید از {buyer.first_name}:\n\n"
             # Pharmacy drugs
                pharmacy_drugs = [
                    item for item in selected_items 
                    if item.get('type') == 'pharmacy_drug'
                ]
                if pharmacy_drugs:
                    offer_message += "💊 داروهای درخواستی از شما:\n"
                    for item in pharmacy_drugs:
                        subtotal = parse_price(item['price']) * item.get('selected_quantity', 1)
                        offer_message += (
                            f"  • {item['name']}\n"
                            f"    تعداد: {item.get('selected_quantity', 1)}\n"
                            f"    قیمت واحد: {item['price']}\n"
                            f"    جمع: {subtotal:,}\n\n"
                        )
                    offer_message += f"💰 جمع کل: {sum(parse_price(i['price'])*i.get('selected_quantity',1) for i in pharmacy_drugs):,}\n\n"
                
                # Buyer drugs
                buyer_drugs = [
                    item for item in selected_items 
                    if item.get('type') == 'buyer_drug'
                ]
                if buyer_drugs:
                    offer_message += "📝 داروهای پیشنهادی خریدار:\n"
                    for item in buyer_drugs:
                        subtotal = parse_price(item['price']) * item.get('selected_quantity', 1)
                        offer_message += (
                            f"  • {item['name']}\n"
                            f"    تعداد: {item.get('selected_quantity', 1)}\n"
                            f"    قیمت واحد: {item['price']}\n"
                            f"    جمع: {subtotal:,}\n\n"
                        )
                    offer_message += f"💰 جمع کل: {sum(parse_price(i['price'])*i.get('selected_quantity',1) for i in buyer_drugs):,}\n\n"
                
                # Compensation items
                comp_items = [
                    item for item in selected_items 
                    if item.get('type') in ('pharmacy_comp', 'buyer_comp')
                ]
                if comp_items:
                    offer_message += "➕ اقلام جبرانی:\n"
                    for item in comp_items:
                        subtotal = parse_price(item['price']) * item.get('selected_quantity', 1)
                        offer_message += (
                            f"  • {item['name']} ({'از شما' if item['type'] == 'pharmacy_comp' else 'از خریدار'})\n"
                            f"    تعداد: {item.get('selected_quantity', 1)}\n"
                            f"    قیمت واحد: {item['price']}\n"
                            f"    جمع: {subtotal:,}\n\n"
                        )
                    offer_message += f"💰 جمع جبران: {sum(parse_price(i['price'])*i.get('selected_quantity',1) for i in comp_items):,}\n\n"
                
                offer_message += (
                    f"💵 تفاوت نهایی: {abs(difference):,}\n\n"
                    f"🆔 کد پیشنهاد: {offer_id}\n"
                    "برای پاسخ به این پیشنهاد از دکمه‌های زیر استفاده کنید:"
                )
                
                # Create response keyboard
                keyboard = [
                    [InlineKeyboardButton("✅ قبول", callback_data=f"offer_accept_{offer_id}")],
                    [InlineKeyboardButton("❌ رد", callback_data=f"offer_reject_{offer_id}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Send notification to pharmacy
                try:
                    await context.bot.send_message(
                        chat_id=pharmacy['id'],
                        text=offer_message,
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    logger.error(f"Failed to notify pharmacy: {e}")
                
                # Prepare success message for buyer
                success_msg = "✅ پیشنهاد شما با موفقیت ارسال شد!\n\n"
                if pharmacy_drugs:
                    success_msg += f"💊 جمع داروهای داروخانه: {sum(parse_price(i['price'])*i.get('selected_quantity',1) for i in pharmacy_drugs):,}\n"
                if buyer_drugs:
                    success_msg += f"📝 جمع داروهای شما: {sum(parse_price(i['price'])*i.get('selected_quantity',1) for i in buyer_drugs):,}\n"
                if comp_items:
                    success_msg += f"➕ جمع جبران: {sum(parse_price(i['price'])*i.get('selected_quantity',1) for i in comp_items):,}\n"
                success_msg += f"💵 تفاوت نهایی: {abs(difference):,}\n"
                success_msg += f"🆔 کد پیگیری: {offer_id}\n"
                
                await query.edit_message_text(success_msg)
                
        except psycopg2.Error as e:
            logger.error(f"Database error: {e}")
            await query.edit_message_text(
                "❌ خطایی در ارسال پیشنهاد رخ داد. لطفا دوباره تلاش کنید."
            )
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            await query.edit_message_text(
                "❌ خطای غیرمنتظره رخ داد. لطفا دوباره تلاش کنید."
            )
        finally:
            if conn:
                conn.close()
        
        return ConversationHandler.END
    
    elif query.data == "edit_selection":
        context.user_data['current_item_index'] = 0
        return await show_two_column_selection(update, context)

async def handle_offer_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("offer_"):
        parts = query.data.split("_")
        action = parts[1]  # accept or reject
        offer_id = int(parts[2])
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                
                # Get offer details
                cursor.execute('''
                SELECT o.*, 
                       u.first_name || ' ' || COALESCE(u.last_name, '') AS buyer_name,
                       u.id AS buyer_id,
                       p.user_id AS pharmacy_id
                FROM offers o
                JOIN users u ON o.buyer_id = u.id
                JOIN pharmacies p ON o.pharmacy_id = p.user_id
                WHERE o.id = %s
                ''', (offer_id,))
                offer = cursor.fetchone()
                
                if not offer:
                    await query.edit_message_text("پیشنهاد یافت نشد")
                    return
                
                if action == "reject":
                    # Update offer status
                    cursor.execute('''
                    UPDATE offers SET status = 'rejected' WHERE id = %s
                    ''', (offer_id,))
                    conn.commit()
                    
                    # Notify buyer
                    try:
                        await context.bot.send_message(
                            chat_id=offer['buyer_id'],
                            text=f"❌ پیشنهاد شما با کد {offer_id} رد شد."
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify buyer: {e}")
                    
                    await query.edit_message_text("پیشنهاد رد شد.")
                    return
                
                elif action == "accept":
                    # Update offer status
                    cursor.execute('''
                    UPDATE offers SET status = 'accepted' WHERE id = %s
                    ''', (offer_id,))
                    
                    # Process drug items
                    cursor.execute('''
                    SELECT drug_name, price, quantity, item_type 
                    FROM offer_items 
                    WHERE offer_id = %s
                    ''', (offer_id,))
                    items = cursor.fetchall()
                    
                    for item in items:
                        if item['item_type'] == 'pharmacy_drug':
                            # Deduct from pharmacy's inventory
                            cursor.execute('''
                            UPDATE drug_items 
                            SET quantity = quantity - %s
                            WHERE user_id = %s AND name = %s AND price = %s
                            ''', (
                                item['quantity'],
                                offer['pharmacy_id'],
                                item['drug_name'],
                                item['price']
                            ))
                        elif item['item_type'] == 'buyer_drug':
                            # Deduct from buyer's inventory
                            cursor.execute('''
                            UPDATE drug_items 
                            SET quantity = quantity - %s
                            WHERE user_id = %s AND name = %s AND price = %s
                            ''', (
                                item['quantity'],
                                offer['buyer_id'],
                                item['drug_name'],
                                item['price']
                            ))
                    
                    # Process compensation items
                    cursor.execute('''
                    SELECT ci.quantity, di.name, di.price, di.user_id
                    FROM compensation_items ci
                    JOIN drug_items di ON ci.drug_id = di.id
                    WHERE ci.offer_id = %s
                    ''', (offer_id,))
                    comp_items = cursor.fetchall()
                    
                    for item in comp_items:
                        # Deduct from owner's inventory
                        cursor.execute('''
                        UPDATE drug_items 
                        SET quantity = quantity - %s
                        WHERE id = %s
                        ''', (
                            item['quantity'],
                            item['id']
                        ))
                    
                    conn.commit()
                    
                    # Prepare notification messages
                    buyer_msg = (
                        f"✅ پیشنهاد شما با کد {offer_id} پذیرفته شد!\n\n"
                        "جزئیات معامله:\n"
                    )
                    
                    pharmacy_msg = (
                        f"✅ پیشنهاد با کد {offer_id} را پذیرفتید!\n\n"
                        "جزئیات معامله:\n"
                    )
                    
                    # Add items to messages
                    cursor.execute('''
                    SELECT oi.drug_name, oi.price, oi.quantity, oi.item_type
                    FROM offer_items oi
                    WHERE oi.offer_id = %s
                    ''', (offer_id,))
                    items = cursor.fetchall()
                    
                    for item in items:
                        line = (
                            f"• {item['drug_name']} ({'از شما' if item['item_type'] == 'pharmacy_drug' else 'از خریدار'})\n"
                            f"  تعداد: {item['quantity']}\n"
                            f"  قیمت: {item['price']}\n\n"
                        )
                        
                        if item['item_type'] == 'pharmacy_drug':
                            buyer_msg += line
                        else:
                            pharmacy_msg += line
                    
                    # Add compensation items
                    cursor.execute('''
                    SELECT di.name, di.price, ci.quantity
                    FROM compensation_items ci
                    JOIN drug_items di ON ci.drug_id = di.id
                    WHERE ci.offer_id = %s
                    ''', (offer_id,))
                    comp_items = cursor.fetchall()
                    
                    if comp_items:
                        buyer_msg += "\n➕ اقلام جبرانی:\n"
                        pharmacy_msg += "\n➕ اقلام جبرانی:\n"
                        
                        for item in comp_items:
                            line = (
                                f"• {item['name']}\n"
                                f"  تعداد: {item['quantity']}\n"
                                f"  قیمت: {item['price']}\n\n"
                            )
                            buyer_msg += line
                            pharmacy_msg += line
                    
                    # Add contact info
                    buyer_msg += f"\n✉️ تماس با داروخانه: @{offer['buyer_name']}"
                    pharmacy_msg += f"\n✉️ تماس با خریدار: @{offer['buyer_name']}"
                    
                    # Send notifications
                    await context.bot.send_message(
                        chat_id=offer['buyer_id'],
                        text=buyer_msg
                    )
                    
                    await context.bot.send_message(
                        chat_id=offer['pharmacy_id'],
                        text=pharmacy_msg
                    )
                    
                    await query.edit_message_text("پیشنهاد با موفقیت پذیرفته شد!")
                    return
                        
        except Exception as e:
            logger.error(f"Error handling offer response: {e}")
            await query.edit_message_text("خطا در پردازش پیشنهاد.")
        finally:
            if conn:
                conn.close()

async def add_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, context)
    await update.message.reply_text(
        "لطفا نام دارویی که می‌خواهید اضافه کنید را جستجو کنید:",
        reply_markup=ReplyKeyboardRemove()
    )
    return States.SEARCH_DRUG_FOR_ADDING

async def search_drug_for_adding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_term = update.message.text.lower().strip()
    context.user_data['search_term'] = search_term

    matched_drugs = []
    for name, price in drug_list:
        if name and search_term in name.lower():
            matched_drugs.append((name, price))

    if not matched_drugs:
        await update.message.reply_text(
            "هیچ دارویی با این نام یافت نشد. لطفا دوباره جستجو کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.SEARCH_DRUG_FOR_ADDING

    context.user_data['matched_drugs'] = matched_drugs
    
    keyboard = []
    for idx, (name, price) in enumerate(matched_drugs[:10]):
        keyboard.append([InlineKeyboardButton(
            f"{name} ({price})", 
            callback_data=f"select_drug_{idx}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back")])
    keyboard.append([InlineKeyboardButton("❌ لغو", callback_data="cancel")])

    message = "نتایج جستجو:\n\n"
    for idx, (name, price) in enumerate(matched_drugs[:10]):
        message += f"{idx+1}. {name} - {price}\n"
    
    if len(matched_drugs) > 10:
        message += f"\n➕ {len(matched_drugs)-10} نتیجه دیگر...\n"

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        message + "\nلطفا از لیست بالا انتخاب کنید:",
        reply_markup=reply_markup
    )
    return States.SELECT_DRUG_FOR_ADDING

async def select_drug_for_adding(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def add_drug_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def save_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    conn = None
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید.")
            return States.ADD_DRUG_QUANTITY
        
        user = update.effective_user
        conn = get_db_connection()
        with conn.cursor() as cursor:
            
            cursor.execute('''
            INSERT INTO drug_items (
                user_id, name, price, date, quantity
            ) VALUES (%s, %s, %s, %s, %s)
            ''', (
                user.id,
                context.user_data['selected_drug']['name'],
                context.user_data['selected_drug']['price'],
                context.user_data['drug_date'],
                quantity
            ))
            conn.commit()
            
            await update.message.reply_text(
                f"✅ دارو با موفقیت اضافه شد!\n\n"
                f"نام: {context.user_data['selected_drug']['name']}\n"
                f"قیمت: {context.user_data['selected_drug']['price']}\n"
                f"تاریخ انقضا: {context.user_data['drug_date']}\n"
                f"تعداد: {quantity}"
            )
            
            # Check for matches with other users' needs
            context.application.create_task(check_for_matches(user.id, context))
            
    except ValueError:
        await update.message.reply_text("لطفا یک عدد صحیح وارد کنید.")
        return States.ADD_DRUG_QUANTITY
    except Exception as e:
        await update.message.reply_text("خطا در ثبت دارو. لطفا دوباره تلاش کنید.")
        logger.error(f"Error saving drug: {e}")
    finally:
        if conn:
            conn.close()
    
    return ConversationHandler.END

async def setup_medical_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, context)
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
            
            # Get all available categories
            cursor.execute('SELECT id, name FROM medical_categories')
            all_categories = cursor.fetchall()
            
            # Get user's current categories
            cursor.execute('''
            SELECT mc.id, mc.name 
            FROM user_categories uc
            JOIN medical_categories mc ON uc.category_id = mc.id
            WHERE uc.user_id = %s
            ''', (update.effective_user.id,))
            user_categories = cursor.fetchall()
            
            user_category_ids = [c['id'] for c in user_categories]
            
            # Create keyboard
            keyboard = []
            for category in all_categories:
                is_selected = category['id'] in user_category_ids
                emoji = "✅ " if is_selected else ""
                keyboard.append([InlineKeyboardButton(
                    f"{emoji}{category['name']}", 
                    callback_data=f"togglecat_{category['id']}"
                )])
            
            keyboard.append([InlineKeyboardButton("💾 ذخیره", callback_data="save_categories")])
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back")])
            
            message = (
                "لطفا شاخه‌های دارویی مورد نظر خود را انتخاب کنید:\n\n"
                "علامت ✅ نشان‌دهنده انتخاب است\n"
                "پس از انتخاب، روی دکمه ذخیره کلیک کنید"
            )
            
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return States.SELECT_NEED_CATEGORY
            
    except Exception as e:
        logger.error(f"Error setting up categories: {e}")
        await update.message.reply_text("خطا در دریافت شاخه‌ها. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

async def toggle_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "back":
        await cancel(update, context)
        return ConversationHandler.END

    if query.data.startswith("togglecat_"):
        category_id = int(query.data.split("_")[1])
        
        if 'selected_categories' not in context.user_data:
            # Initialize with user's current categories
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor() as cursor:
                    cursor.execute('''
                    SELECT category_id 
                    FROM user_categories 
                    WHERE user_id = %s
                    ''', (update.effective_user.id,))
                    context.user_data['selected_categories'] = [row[0] for row in cursor.fetchall()]
            except Exception as e:
                logger.error(f"Error getting user categories: {e}")
                context.user_data['selected_categories'] = []
            finally:
                if conn:
                    conn.close()
        
        if category_id in context.user_data['selected_categories']:
            context.user_data['selected_categories'].remove(category_id)
        else:
            context.user_data['selected_categories'].append(category_id)
        
        # Refresh the category selection view
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('SELECT id, name FROM medical_categories')
                all_categories = cursor.fetchall()
                
                keyboard = []
                for category in all_categories:
                    is_selected = category['id'] in context.user_data.get('selected_categories', [])
                    emoji = "✅ " if is_selected else ""
                    keyboard.append([InlineKeyboardButton(
                        f"{emoji}{category['name']}", 
                        callback_data=f"togglecat_{category['id']}"
                    )])
                
                keyboard.append([InlineKeyboardButton("💾 ذخیره", callback_data="save_categories")])
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back")])
                
                await query.edit_message_text(
                    "لطفا شاخه‌های دارویی مورد نظر خود را انتخاب کنید:\n\n"
                    "علامت ✅ نشان‌دهنده انتخاب است\n"
                    "پس از انتخاب، روی دکمه ذخیره کلیک کنید",
                    reply_markup=InlineKeyboardMarkup(keyboard))
                
        except Exception as e:
            logger.error(f"Error refreshing categories: {e}")
            await query.edit_message_text("خطا در بروزرسانی لیست. لطفا دوباره تلاش کنید.")
        finally:
            if conn:
                conn.close()

async def save_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if 'selected_categories' not in context.user_data:
        await query.edit_message_text("خطا در ذخیره‌سازی. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            
            # Clear existing categories
            cursor.execute('''
            DELETE FROM user_categories WHERE user_id = %s
            ''', (update.effective_user.id,))
            
            # Add selected categories
            for category_id in context.user_data['selected_categories']:
                cursor.execute('''
                INSERT INTO user_categories (user_id, category_id)
                VALUES (%s, %s)
                ''', (update.effective_user.id, category_id))
            
            conn.commit()
            
            # Get category names for message
            cursor.execute('''
            SELECT name FROM medical_categories WHERE id = ANY(%s)
            ''', (context.user_data['selected_categories'],))
            
            category_names = [row[0] for row in cursor.fetchall()]
            
            await query.edit_message_text(
                f"✅ شاخه‌های دارویی با موفقیت ذخیره شدند:\n\n"
                f"{', '.join(category_names)}"
            )
            
    except Exception as e:
        logger.error(f"Error saving categories: {e}")
        await query.edit_message_text("خطا در ذخیره‌سازی. لطفا دوباره تلاش کنید.")
    finally:
        if conn:
            conn.close()
    
    return ConversationHandler.END

async def list_my_drugs(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                    message += (
                        f"• {drug['name']}\n"
                        f"  قیمت: {drug['price']}\n"
                        f"  تاریخ انقضا: {drug['date']}\n"
                        f"  موجودی: {drug['quantity']}\n\n"
                    )
                
                keyboard = [
                    [InlineKeyboardButton("✏️ ویرایش داروها", callback_data="edit_drugs")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
                ]
                
                await update.message.reply_text(
                    message,
                    reply_markup=InlineKeyboardMarkup(keyboard))
                return States.EDIT_ITEM
            else:
                await update.message.reply_text("شما هنوز هیچ دارویی اضافه نکرده‌اید.")
                
    except Exception as e:
        logger.error(f"Error listing drugs: {e}")
        await update.message.reply_text("خطا در دریافت لیست داروها. لطفا دوباره تلاش کنید.")
    finally:
        if conn:
            conn.close()

async def edit_drugs(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            
            keyboard = []
            for drug in drugs:
                keyboard.append([InlineKeyboardButton(
                    f"{drug['name']} ({drug['quantity']})",
                    callback_data=f"edit_drug_{drug['id']}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back")])
            
            await query.edit_message_text(
                "لطفا دارویی که می‌خواهید ویرایش کنید را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard))
            return States.EDIT_ITEM
            
    except Exception as e:
        logger.error(f"Error in edit_drugs: {e}")
        await query.edit_message_text("خطا در دریافت لیست داروها.")
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

async def edit_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                    [InlineKeyboardButton("✏️ ویرایش نام", callback_data="edit_name")],
                    [InlineKeyboardButton("✏️ ویرایش قیمت", callback_data="edit_price")],
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
                return States.EDIT_ITEM
                
        except Exception as e:
            logger.error(f"Error getting drug details: {e}")
            await query.edit_message_text("خطا در دریافت اطلاعات دارو.")
            return ConversationHandler.END
        finally:
            if conn:
                conn.close()
async def handle_drug_edit_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "back_to_list":
        return await edit_drugs(update, context)
    
    drug = context.user_data.get('editing_drug')
    if not drug:
        await query.edit_message_text("اطلاعات دارو یافت نشد.")
        return ConversationHandler.END
    
    if query.data == "edit_name":
        await query.edit_message_text(
            f"نام فعلی: {drug['name']}\n\n"
            "لطفا نام جدید را وارد کنید:"
        )
        context.user_data['edit_field'] = 'name'
        return States.EDIT_ITEM
    
    elif query.data == "edit_price":
        await query.edit_message_text(
            f"قیمت فعلی: {drug['price']}\n\n"
            "لطفا قیمت جدید را وارد کنید:"
        )
        context.user_data['edit_field'] = 'price'
        return States.EDIT_ITEM
    
    elif query.data == "edit_date":
        await query.edit_message_text(
            f"تاریخ فعلی: {drug['date']}\n\n"
            "لطفا تاریخ جدید را وارد کنید (مثال: 1403/05/15):"
        )
        context.user_data['edit_field'] = 'date'
        return States.EDIT_ITEM
    
    elif query.data == "edit_quantity":
        await query.edit_message_text(
            f"تعداد فعلی: {drug['quantity']}\n\n"
            "لطفا تعداد جدید را وارد کنید:"
        )
        context.user_data['edit_field'] = 'quantity'
        return States.EDIT_ITEM
    
    elif query.data == "delete_drug":
        keyboard = [
            [InlineKeyboardButton("✅ بله، حذف شود", callback_data="confirm_delete")],
            [InlineKeyboardButton("❌ خیر، انصراف", callback_data="cancel_delete")]
        ]
        
        await query.edit_message_text(
            f"آیا مطمئن هستید که می‌خواهید داروی {drug['name']} را حذف کنید؟",
            reply_markup=InlineKeyboardMarkup(keyboard))
        return States.EDIT_ITEM

async def save_drug_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    edit_field = context.user_data.get('edit_field')
    new_value = update.message.text
    drug = context.user_data.get('editing_drug')
    
    if not edit_field or not drug:
        await update.message.reply_text("خطا در ویرایش. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
    
    # Validate inputs
    if edit_field == 'quantity':
        try:
            new_value = int(new_value)
            if new_value <= 0:
                await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید.")
                return States.EDIT_ITEM
        except ValueError:
            await update.message.reply_text("لطفا یک عدد صحیح وارد کنید.")
            return States.EDIT_ITEM
    elif edit_field == 'date':
        if not re.match(r'^\d{4}/\d{2}/\d{2}$', new_value):
            await update.message.reply_text("فرمت تاریخ نامعتبر است. لطفا به صورت 1403/05/15 وارد کنید.")
            return States.EDIT_ITEM
    
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
            
            # Update the context drug data
            drug[edit_field] = new_value
            
    except Exception as e:
        logger.error(f"Error updating drug: {e}")
        await update.message.reply_text("خطا در ویرایش دارو. لطفا دوباره تلاش کنید.")
    finally:
        if conn:
            conn.close()
    
    # Return to edit menu
    keyboard = [
        [InlineKeyboardButton("✏️ ویرایش نام", callback_data="edit_name")],
        [InlineKeyboardButton("✏️ ویرایش قیمت", callback_data="edit_price")],
        [InlineKeyboardButton("✏️ ویرایش تاریخ", callback_data="edit_date")],
        [InlineKeyboardButton("✏️ ویرایش تعداد", callback_data="edit_quantity")],
        [InlineKeyboardButton("🗑️ حذف دارو", callback_data="delete_drug")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_list")]
    ]
    
    await update.message.reply_text(
        f"ویرایش دارو:\n\n"
        f"نام: {drug['name']}\n"
        f"قیمت: {drug['price']}\n"
        f"تاریخ انقضا: {drug['date']}\n"
        f"تعداد: {drug['quantity']}\n\n"
        "لطفا گزینه مورد نظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard))
    return States.EDIT_ITEM

async def handle_drug_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_delete":
        return await edit_drug_item(update, context)
    
    drug = context.user_data.get('editing_drug')
    if not drug:
        await query.edit_message_text("اطلاعات دارو یافت نشد.")
        return ConversationHandler.END
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('''
            DELETE FROM drug_items 
            WHERE id = %s AND user_id = %s
            ''', (drug['id'], update.effective_user.id))
            conn.commit()
            
            await query.edit_message_text(
                f"✅ داروی {drug['name']} با موفقیت حذف شد."
            )
            
    except Exception as e:
        logger.error(f"Error deleting drug: {e}")
        await query.edit_message_text("خطا در حذف دارو. لطفا دوباره تلاش کنید.")
    finally:
        if conn:
            conn.close()
    
    return await list_my_drugs(update, context)

async def add_need(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, context)
    await update.message.reply_text("لطفا نام دارویی که نیاز دارید را وارد کنید:")
    return States.ADD_NEED_NAME

async def save_need_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['need_name'] = update.message.text
    await update.message.reply_text("لطفا توضیحاتی درباره این نیاز وارد کنید (اختیاری):")
    return States.ADD_NEED_DESC

async def save_need_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['need_desc'] = update.message.text
    await update.message.reply_text("لطفا تعداد مورد نیاز را وارد کنید:")
    return States.ADD_NEED_QUANTITY

async def save_need(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                
                # Check for matches with available drugs
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

async def list_my_needs(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                return States.EDIT_ITEM
            else:
                await update.message.reply_text("شما هنوز هیچ نیازی ثبت نکرده‌اید.")
                
    except Exception as e:
        logger.error(f"Error listing needs: {e}")
        await update.message.reply_text("خطا در دریافت لیست نیازها. لطفا دوباره تلاش کنید.")
    finally:
        if conn:
            conn.close()

async def edit_needs(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            return States.EDIT_ITEM
            
    except Exception as e:
        logger.error(f"Error in edit_needs: {e}")
        await query.edit_message_text("خطا در دریافت لیست نیازها.")
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

async def edit_need_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                return States.EDIT_ITEM
                
        except Exception as e:
            logger.error(f"Error getting need details: {e}")
            await query.edit_message_text("خطا در دریافت اطلاعات نیاز.")
            return ConversationHandler.END
        finally:
            if conn:
                conn.close()

async def handle_need_edit_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        return States.EDIT_ITEM
    
    elif query.data == "edit_need_desc":
        await query.edit_message_text(
            f"توضیحات فعلی: {need['description'] or 'بدون توضیح'}\n\n"
            "لطفا توضیحات جدید را وارد کنید:"
        )
        context.user_data['edit_field'] = 'description'
        return States.EDIT_ITEM
    
    elif query.data == "edit_need_quantity":
        await query.edit_message_text(
            f"تعداد فعلی: {need['quantity']}\n\n"
            "لطفا تعداد جدید را وارد کنید:"
        )
        context.user_data['edit_field'] = 'quantity'
        return States.EDIT_ITEM
    
    elif query.data == "delete_need":
        keyboard = [
            [InlineKeyboardButton("✅ بله، حذف شود", callback_data="confirm_need_delete")],
            [InlineKeyboardButton("❌ خیر، انصراف", callback_data="cancel_need_delete")]
        ]
        
        await query.edit_message_text(
            f"آیا مطمئن هستید که می‌خواهید نیاز {need['name']} را حذف کنید؟",
            reply_markup=InlineKeyboardMarkup(keyboard))
        return States.EDIT_ITEM

async def save_need_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    edit_field = context.user_data.get('edit_field')
    new_value = update.message.text
    need = context.user_data.get('editing_need')
    
    if not edit_field or not need:
        await update.message.reply_text("خطا در ویرایش. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
    
    # Validate inputs
    if edit_field == 'quantity':
        try:
            new_value = int(new_value)
            if new_value <= 0:
                await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید.")
                return States.EDIT_ITEM
        except ValueError:
            await update.message.reply_text("لطفا یک عدد صحیح وارد کنید.")
            return States.EDIT_ITEM
    
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
            
            # Update the context need data
            need[edit_field] = new_value
            
    except Exception as e:
        logger.error(f"Error updating need: {e}")
        await update.message.reply_text("خطا در ویرایش نیاز. لطفا دوباره تلاش کنید.")
    finally:
        if conn:
            conn.close()
    
    # Return to edit menu
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
    return States.EDIT_ITEM

async def handle_need_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def handle_match_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("view_match_"):
        parts = query.data.split("_")
        drug_id = int(parts[2])
        need_id = int(parts[3])
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                
                # Get drug details
                cursor.execute('''
                SELECT di.*, 
                       p.name AS pharmacy_name
                FROM drug_items di
                JOIN pharmacies p ON di.user_id = p.user_id
                WHERE di.id = %s
                ''', (drug_id,))
                drug = cursor.fetchone()
                
                if not drug:
                    await query.edit_message_text("دارو یافت نشد.")
                    return
                
                # Get need details
                cursor.execute('''
                SELECT * FROM user_needs WHERE id = %s
                ''', (need_id,))
                need = cursor.fetchone()
                
                if not need:
                    await query.edit_message_text("نیاز یافت نشد.")
                    return
                
                # Prepare message
                message = (
                    "🔔 تطابق یافت شده:\n\n"
                    f"نیاز شما: {need['name']}\n"
                    f"توضیحات نیاز: {need['description'] or 'بدون توضیح'}\n"
                    f"تعداد مورد نیاز: {need['quantity']}\n\n"
                    f"داروی موجود: {drug['name']}\n"
                    f"قیمت: {drug['price']}\n"
                    f"تاریخ انقضا: {drug['date']}\n"
                    f"موجودی: {drug['quantity']}\n"
                    f"داروخانه: {drug['pharmacy_name']}\n\n"
                    "آیا مایل به تبادل این دارو هستید؟"
                )
                
                keyboard = [
                    [InlineKeyboardButton("تبادل این دارو", callback_data=f"buy_match_{drug_id}")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
                ]
                
                await query.edit_message_text(
                    message,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                # Store drug and need in context for purchase flow
                context.user_data['matched_drug'] = dict(drug)
                context.user_data['matched_need'] = dict(need)
                
        except Exception as e:
            logger.error(f"Error handling match view: {e}")
            await query.edit_message_text("خطا در نمایش اطلاعات تطابق.")
        finally:
            if conn:
                conn.close()

async def handle_match_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "back":
        await cancel(update, context)
        return

    if query.data.startswith("buy_match_"):
        drug_id = int(query.data.split("_")[2])
        drug = context.user_data.get('matched_drug')
        need = context.user_data.get('matched_need')
        
        if not drug or not need:
            await query.edit_message_text("خطا در اطلاعات تبادل. لطفا دوباره تلاش کنید.")
            return
        
        # Set up the purchase flow similar to regular search
        context.user_data['selected_pharmacy'] = {
            'id': drug['user_id'],
            'name': drug['pharmacy_name']
        }
        
        # Get pharmacy's drugs (just the matched one)
        context.user_data['pharmacy_drugs'] = [{
            'id': drug['id'],
            'user_id': drug['user_id'],
            'name': drug['name'],
            'price': drug['price'],
            'date': drug['date'],
            'quantity': drug['quantity']
        }]
        
        # Get buyer's drugs
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                SELECT id, name, price, quantity 
                FROM drug_items 
                WHERE user_id = %s AND quantity > 0
                ''', (update.effective_user.id,))
                buyer_drugs = cursor.fetchall()
                context.user_data['buyer_drugs'] = [dict(row) for row in buyer_drugs]
                
                # Get pharmacy's medical categories
                cursor.execute('''
                SELECT mc.id, mc.name 
                FROM user_categories uc
                JOIN medical_categories mc ON uc.category_id = mc.id
                WHERE uc.user_id = %s
                ''', (drug['user_id'],))
                pharmacy_categories = cursor.fetchall()
                context.user_data['pharmacy_categories'] = [dict(row) for row in pharmacy_categories]
                
        except Exception as e:
            logger.error(f"Error fetching data for purchase: {e}")
            context.user_data['buyer_drugs'] = []
            context.user_data['pharmacy_categories'] = []
        finally:
            if conn:
                conn.close()
        
        # Auto-select the matched drug
        context.user_data['selected_items'] = [{
            'id': drug['id'],
            'name': drug['name'],
            'price': drug['price'],
            'quantity': drug['quantity'],
            'type': 'pharmacy_drug',
            'selected_quantity': min(need['quantity'], drug['quantity'])
        }]
        
        return await show_two_column_selection(update, context)

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, context)
    await update.message.reply_text("لطفا نام داروخانه را وارد کنید:")
    return States.REGISTER_PHARMACY_NAME

async def register_pharmacy_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['pharmacy_name'] = update.message.text
    await update.message.reply_text("لطفا نام مسئول داروخانه را وارد کنید:")
    return States.REGISTER_FOUNDER_NAME

async def register_founder_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['founder_name'] = update.message.text
    await update.message.reply_text("لطفا تصویر کارت ملی را ارسال کنید:")
    return States.REGISTER_NATIONAL_CARD

async def register_national_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("لطفا تصویر کارت ملی را ارسال کنید.")
        return States.REGISTER_NATIONAL_CARD
    
    file = await context.bot.get_file(update.message.photo[-1].file_id)
    file_path = await download_file(file, "national_card", update.effective_user.id)
    context.user_data['national_card_image'] = file_path
    
    await update.message.reply_text("لطفا تصویر پروانه کسب را ارسال کنید:")
    return States.REGISTER_LICENSE

async def register_license(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("لطفا تصویر پروانه کسب را ارسال کنید.")
        return States.REGISTER_LICENSE
    
    file = await context.bot.get_file(update.message.photo[-1].file_id)
    file_path = await download_file(file, "license", update.effective_user.id)
    context.user_data['license_image'] = file_path
    
    await update.message.reply_text("لطفا تصویر کارت نظام پزشکی را ارسال کنید:")
    return States.REGISTER_MEDICAL_CARD

async def register_medical_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("لطفا تصویر کارت نظام پزشکی را ارسال کنید.")
        return States.REGISTER_MEDICAL_CARD
    
    file = await context.bot.get_file(update.message.photo[-1].file_id)
    file_path = await download_file(file, "medical_card", update.effective_user.id)
    context.user_data['medical_card_image'] = file_path
    
    await update.message.reply_text("لطفا شماره تلفن همراه را وارد کنید:")
    return States.REGISTER_PHONE

async def register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    if not re.match(r'^09\d{9}$', phone):
        await update.message.reply_text("شماره تلفن نامعتبر است. لطفا شماره را به صورت 09123456789 وارد کنید.")
        return States.REGISTER_PHONE
    
    context.user_data['phone'] = phone
    
    # Generate verification code
    verification_code = str(random.randint(100000, 999999))
    verification_codes[update.effective_user.id] = verification_code
    
    await update.message.reply_text(
        f"کد تایید شما: {verification_code}\n\n"
        "لطفا این کد را برای فروشنده ارسال کرده و پس از تایید، کد را برای ما ارسال کنید."
    )
    return States.VERIFICATION_CODE

async def verify_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_code = update.message.text
    correct_code = verification_codes.get(update.effective_user.id)
    
    if user_code == correct_code:
        # Save registration data
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Generate unique admin code for pharmacy
                admin_code = str(random.randint(100000, 999999))
                
                cursor.execute('''
                INSERT INTO pharmacies (
                    user_id, name, founder_name, national_card_image,
                    license_image, medical_card_image, phone, admin_code
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''', (
                    update.effective_user.id,
                    context.user_data['pharmacy_name'],
                    context.user_data['founder_name'],
                    context.user_data['national_card_image'],
                    context.user_data['license_image'],
                    context.user_data['medical_card_image'],
                    context.user_data['phone'],
                    admin_code
                ))
                
                # Mark user as verified
                cursor.execute('''
                UPDATE users 
                SET is_verified = TRUE, verification_method = 'code'
                WHERE id = %s
                ''', (update.effective_user.id,))
                
                conn.commit()
                
                await update.message.reply_text(
                    "✅ اطلاعات شما با موفقیت ثبت شد!\n\n"
                    f"کد ادمین داروخانه شما: {admin_code}\n\n"
                    "در حال حاضر حساب شما در انتظار تایید مدیریت است. پس از تایید می‌توانید از ربات استفاده کنید."
                )
                
                # Notify admin
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=f"📝 درخواست ثبت نام جدید:\n\n"
                             f"🔹 کاربر: @{update.effective_user.username}\n"
                             f"🔹 داروخانه: {context.user_data['pharmacy_name']}\n"
                             f"🔹 مسئول: {context.user_data['founder_name']}\n"
                             f"🔹 کد ادمین: {admin_code}\n\n"
                             f"برای تایید:\n"
                             f"/approve_{update.effective_user.id}\n\n"
                             f"برای رد:\n"
                             f"/reject_{update.effective_user.id}"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify admin: {e}")
                
        except Exception as e:
            logger.error(f"Error saving registration: {e}")
            await update.message.reply_text("خطا در ثبت اطلاعات. لطفا دوباره تلاش کنید.")
        finally:
            if conn:
                conn.close()
        
        return ConversationHandler.END
    else:
        await update.message.reply_text("کد تایید نامعتبر است. لطفا دوباره تلاش کنید.")
        return States.VERIFICATION_CODE

async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لطفا شماره تلفن همراه را وارد کنید:")
    return States.REGISTER_PHONE

async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    parts = update.message.text.split('_')
    if len(parts) != 2:
        await update.message.reply_text("فرمت دستور نامعتبر است.")
        return
    
    user_id = int(parts[1])
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Check if already approved
            cursor.execute('''
            SELECT verified FROM pharmacies WHERE user_id = %s
            ''', (user_id,))
            result = cursor.fetchone()
            
            if result and result[0]:
                await update.message.reply_text("این داروخانه قبلا تایید شده است.")
                return
            
            # Approve pharmacy
            cursor.execute('''
            UPDATE pharmacies 
            SET verified = TRUE, verified_at = CURRENT_TIMESTAMP, admin_id = %s
            WHERE user_id = %s
            ''', (update.effective_user.id, user_id))
            
            # Update user verification status
            cursor.execute('''
            UPDATE users 
            SET is_verified = TRUE 
            WHERE id = %s
            ''', (user_id,))
            
            conn.commit()
            
            # Get pharmacy info for notification
            cursor.execute('''
            SELECT name, admin_code FROM pharmacies WHERE user_id = %s
            ''', (user_id,))
            pharmacy = cursor.fetchone()
            
            if pharmacy:
                # Notify user
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ داروخانه {pharmacy[0]} توسط مدیریت تایید شد!\n\n"
                             f"کد ادمین شما: {pharmacy[1]}\n\n"
                             f"اکنون می‌توانید از تمام امکانات ربات استفاده کنید."
                    )
                except Exception as e:
                    logger.error(f"Failed to notify user: {e}")
            
            await update.message.reply_text(f"داروخانه با شناسه {user_id} تایید شد.")
            
    except Exception as e:
        logger.error(f"Error approving user: {e}")
        await update.message.reply_text("خطا در تایید کاربر.")
    finally:
        if conn:
            conn.close()

async def reject_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    parts = update.message.text.split('_')
    if len(parts) != 2:
        await update.message.reply_text("فرمت دستور نامعتبر است.")
        return
    
    user_id = int(parts[1])
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Get pharmacy info before deleting
            cursor.execute('''
            SELECT name FROM pharmacies WHERE user_id = %s
            ''', (user_id,))
            pharmacy = cursor.fetchone()
            
            # Delete pharmacy registration
            cursor.execute('''
            DELETE FROM pharmacies WHERE user_id = %s
            ''', (user_id,))
            
            # Reset user verification
            cursor.execute('''
            UPDATE users 
            SET is_verified = FALSE, verification_method = NULL
            WHERE id = %s
            ''', (user_id,))
            
            conn.commit()
            
            # Notify user
            if pharmacy:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"❌ درخواست ثبت نام داروخانه {pharmacy[0]} رد شد.\n\n"
                             "لطفا برای اطلاعات بیشتر با پشتیبانی تماس بگیرید."
                    )
                except Exception as e:
                    logger.error(f"Failed to notify user: {e}")
            
            await update.message.reply_text(f"کاربر با شناسه {user_id} رد شد.")
            
    except Exception as e:
        logger.error(f"Error rejecting user: {e}")
        await update.message.reply_text("خطا در رد کاربر.")
    finally:
        if conn:
            conn.close()

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("عملیات لغو شد.", reply_markup=ReplyKeyboardRemove())
    elif update.callback_query:
        await update.callback_query.edit_message_text("عملیات لغو شد.")
    
    context.user_data.clear()
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors and send a more friendly message to users."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    # Log the full traceback
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = ''.join(tb_list)
    logger.error(f"Full traceback:\n{tb_string}")
    
    # Don't send error messages for callback queries if update is None
    if update is None:
        logger.error("Update is None, can't send error message to user")
        return
    
    try:
        # Different error handling for different error types
        if isinstance(context.error, TimedOut):
            error_msg = "⏳ زمان پاسخگویی به درخواست شما به پایان رسید. لطفا دوباره تلاش کنید."
        elif isinstance(context.error, psycopg2.Error):
            error_msg = "⚠️ خطایی در ارتباط با پایگاه داده رخ داد. لطفا چند لحظه صبر کنید و دوباره تلاش کنید."
        elif isinstance(context.error, ValueError):
            error_msg = "⚠️ مقدار وارد شده نامعتبر است. لطفا اطلاعات را بررسی کرده و مجددا ارسال نمایید."
        else:
            error_msg = "⚠️ خطایی رخ داده است. لطفا دوباره تلاش کنید."
        
        # Send appropriate message to user
        if update.callback_query:
            await update.callback_query.answer(error_msg, show_alert=True)
        elif update.message:
            await update.message.reply_text(error_msg)
            
    except Exception as e:
        logger.error(f"Failed to handle error: {e}")
        try:
            if update.message:
                await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        except Exception as fallback_error:
            logger.error(f"Even fallback error handling failed: {fallback_error}")

def main():
    application = Application.builder().token("7551102128:AAGYSOLzITvCfiCNM1i1elNTPtapIcbF8W4").build()
    
    # Add middleware
    application.add_handler(UserApprovalMiddleware(), group=-1)
    
    # Drug search and trading handler
    trade_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^جستجوی دارو$'), search_drug),
            CallbackQueryHandler(handle_match_purchase, pattern=r"^buy_match_\d+$")
        ],
        states={
            States.SEARCH_DRUG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search)],
            States.SELECT_PHARMACY: [CallbackQueryHandler(select_pharmacy)],
            States.SELECT_ITEMS: [CallbackQueryHandler(select_items)],
            States.CONFIRM_TOTALS: [CallbackQueryHandler(confirm_totals)],
            States.COMPENSATION_SELECTION: [CallbackQueryHandler(handle_compensation_selection)],
            States.COMPENSATION_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_compensation_quantity)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )

    # Drug addition handler
    add_drug_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^اضافه کردن دارو$'), add_drug_item)],
        states={
            States.SEARCH_DRUG_FOR_ADDING: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_drug_for_adding)],
            States.SELECT_DRUG_FOR_ADDING: [CallbackQueryHandler(select_drug_for_adding)],
            States.ADD_DRUG_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_drug_date)],
            States.ADD_DRUG_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_drug_item)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )

    # Medical categories setup handler
    categories_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^تنظیم شاخه‌های دارویی$'), setup_medical_categories)],
        states={
            States.SELECT_NEED_CATEGORY: [CallbackQueryHandler(toggle_category)],
        },
        fallbacks=[
            CallbackQueryHandler(save_categories, pattern="^save_categories$"),
            CommandHandler('cancel', cancel)
        ],
        per_message=False
    )

    # Need addition handler
    need_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^ثبت نیاز جدید$'), add_need)],
        states={
            States.ADD_NEED_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_need_name)],
            States.ADD_NEED_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_need_desc)],
            States.ADD_NEED_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_need)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )

    # Registration handler
    registration_conv = ConversationHandler(
        entry_points=[CommandHandler('register', register)],
        states={
            States.REGISTER_PHARMACY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_pharmacy_name)],
            States.REGISTER_FOUNDER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_founder_name)],
            States.REGISTER_NATIONAL_CARD: [MessageHandler(filters.PHOTO, register_national_card)],
            States.REGISTER_LICENSE: [MessageHandler(filters.PHOTO, register_license)],
            States.REGISTER_MEDICAL_CARD: [MessageHandler(filters.PHOTO, register_medical_card)],
            States.REGISTER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_phone)],
            States.VERIFICATION_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_code)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )

    # Verification handler
    verification_conv = ConversationHandler(
        entry_points=[CommandHandler('verify', verify_command)],
        states={
            States.REGISTER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_phone)],
            States.VERIFICATION_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_code)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )

    # Admin verification handler
    admin_verify_conv = ConversationHandler(
        entry_points=[
            CommandHandler('admin_verify', admin_verify_start),
            CallbackQueryHandler(admin_verify_start, pattern="^admin_verify$")
        ],
        states={
            States.ADMIN_VERIFICATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_verify_code)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )

    # Admin Excel upload handler
    admin_excel_conv = ConversationHandler(
        entry_points=[CommandHandler('upload_excel', upload_excel_start)],
        states={
            States.ADMIN_UPLOAD_EXCEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_excel_upload),
                MessageHandler(filters.Document.ALL, handle_excel_upload)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )

    # Edit items handler
    edit_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(edit_drugs, pattern="^edit_drugs$"),
            CallbackQueryHandler(edit_needs, pattern="^edit_needs$")
        ],
        states={
            States.EDIT_ITEM: [
                CallbackQueryHandler(edit_drug_item, pattern=r"^edit_drug_\d+$"),
                CallbackQueryHandler(edit_need_item, pattern=r"^edit_need_\d+$"),
                CallbackQueryHandler(handle_drug_edit_action),
                CallbackQueryHandler(handle_need_edit_action),
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_drug_edit),
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_need_edit),
                CallbackQueryHandler(handle_drug_deletion, pattern=r"^confirm_delete$"),
                CallbackQueryHandler(handle_need_deletion, pattern=r"^confirm_need_delete$")
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )

    # Add all handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(trade_conv)
    application.add_handler(add_drug_conv)
    application.add_handler(categories_conv)
    application.add_handler(need_conv)
    application.add_handler(registration_conv)
    application.add_handler(verification_conv)
    application.add_handler(admin_verify_conv)
    application.add_handler(admin_excel_conv)
    application.add_handler(edit_conv)
    
    # List handlers
    application.add_handler(MessageHandler(filters.Regex('^لیست داروهای من$'), list_my_drugs))
    application.add_handler(MessageHandler(filters.Regex('^لیست نیازهای من$'), list_my_needs))
    
    # Admin commands
    application.add_handler(CommandHandler("approve", approve_user))
    application.add_handler(CommandHandler("reject", reject_user))
    
    # Offer response handler
    application.add_handler(CallbackQueryHandler(
        handle_offer_response, 
        pattern=r"^offer_(accept|reject)_\d+$"
    ))
    
    # Match notification handler
    application.add_handler(CallbackQueryHandler(
        handle_match_view,
        pattern=r"^view_match_\d+_\d+$"
    ))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    application.run_polling()

if __name__ == '__main__':
    main()
