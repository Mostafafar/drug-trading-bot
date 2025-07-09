import time
import re
import sqlite3
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

logger = logging.getLogger(__name__)

# Initialize paths and directories
current_dir = Path(__file__).parent
excel_file = current_dir / "DrugPrices.xlsx"
PHOTO_STORAGE = "registration_docs"
DB_FILE = current_dir / "drug_trading.db"

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
    SELECT_SELLER = auto()
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
ADMIN_SECRET_CODE = "12345"  # 5-digit admin verification code

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
            conn = sqlite3.connect(
                DB_FILE,
                timeout=30,
                isolation_level=None,
                check_same_thread=False
            )
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.row_factory = sqlite3.Row
            
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not cursor.fetchall():
                raise sqlite3.Error("No tables found in database")
                
            return conn
            
        except sqlite3.Error as e:
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
    raise sqlite3.Error("Unknown database connection error")

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

def initialize_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Users table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            username TEXT,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_verified BOOLEAN DEFAULT FALSE,
            verification_code TEXT,
            verification_method TEXT
        )''')
        
        # Drug items table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS drug_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            price TEXT,
            date TEXT,
            quantity INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')
        
        # Medical categories table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS medical_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )''')
        
        # User categories (many-to-many)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_categories (
            user_id INTEGER,
            category_id INTEGER,
            PRIMARY KEY (user_id, category_id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(category_id) REFERENCES medical_categories(id)
        )''')
        
        # Offers table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER,
            buyer_id INTEGER,
            status TEXT DEFAULT 'pending',
            total_price REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(seller_id) REFERENCES users(id),
            FOREIGN KEY(buyer_id) REFERENCES users(id)
        )''')
        
        # Offer items table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS offer_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_id INTEGER,
            drug_name TEXT,
            price TEXT,
            quantity INTEGER,
            item_type TEXT DEFAULT 'drug',
            FOREIGN KEY(offer_id) REFERENCES offers(id)
        )''')
        
        # Compensation items table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS compensation_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_id INTEGER,
            drug_id INTEGER,
            quantity INTEGER,
            FOREIGN KEY(offer_id) REFERENCES offers(id),
            FOREIGN KEY(drug_id) REFERENCES drug_items(id)
        )''')
        
        # User registrations table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            pharmacy_name TEXT,
            founder_name TEXT,
            national_card_image TEXT,
            license_image TEXT,
            medical_card_image TEXT,
            phone TEXT,
            address TEXT,
            location_lat REAL,
            location_lng REAL,
            status TEXT DEFAULT 'pending',
            admin_username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Approved users table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS approved_users (
            user_id INTEGER PRIMARY KEY,
            approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verification_method TEXT
        )''')
        
        # User needs table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_needs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            description TEXT,
            quantity INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')
        
        # Auto-match notifications table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS match_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            drug_id INTEGER,
            need_id INTEGER,
            similarity_score REAL,
            notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(drug_id) REFERENCES drug_items(id),
            FOREIGN KEY(need_id) REFERENCES user_needs(id)
        )''')
        
        # Admin settings table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            excel_url TEXT,
            last_updated TIMESTAMP
        )''')
        
        # Insert default medical categories
        default_categories = ['اعصاب', 'قلب', 'ارتوپد', 'زنان', 'گوارش', 'پوست', 'اطفال']
        for category in default_categories:
            cursor.execute('''
            INSERT OR IGNORE INTO medical_categories (name) VALUES (?)
            ''', (category,))
        
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        conn.rollback()
    finally:
        conn.close()

initialize_db()
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
            
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM approved_users WHERE user_id = ?', (update.effective_user.id,))
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
            conn.close()

async def ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT id FROM users WHERE id = ?', (user.id,))
        if not cursor.fetchone():
            cursor.execute('''
            INSERT INTO users (id, first_name, last_name, username)
            VALUES (?, ?, ?, ?)
            ''', (user.id, user.first_name, user.last_name, user.username))
        else:
            # Update last active time
            cursor.execute('''
            UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE id = ?
            ''', (user.id,))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error ensuring user: {e}")
        conn.rollback()
    finally:
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
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Get user's needs
        cursor.execute('''
        SELECT id, name, quantity 
        FROM user_needs 
        WHERE user_id = ?
        ''', (user_id,))
        needs = cursor.fetchall()
        
        if not needs:
            return
        
        # Get all available drugs from other users
        cursor.execute('''
        SELECT f.id, f.name, f.price, f.quantity, 
               u.id as seller_id, 
               u.first_name || ' ' || COALESCE(u.last_name, '') as seller_name
        FROM drug_items f
        JOIN users u ON f.user_id = u.id
        WHERE f.user_id != ? AND f.quantity > 0
        ORDER BY f.created_at DESC
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
                WHERE user_id = ? AND drug_id = ? AND need_id = ?
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
                    f"فروشنده: {match['drug']['seller_name']}\n"
                    f"قیمت: {match['drug']['price']}\n"
                    f"موجودی: {match['drug']['quantity']}\n\n"
                    "برای مشاهده جزئیات و خرید، روی دکمه زیر کلیک کنید:"
                )
                
                keyboard = [[
                    InlineKeyboardButton(
                        "مشاهده و خرید",
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
                ) VALUES (?, ?, ?, ?)
                ''', (
                    user_id,
                    match['drug']['id'],
                    match['need']['id'],
                    match['similarity']
                ))
                conn.commit()
                
            except Exception as e:
                logger.error(f"Failed to notify seller: {e}")
                conn.rollback()
                
    except Exception as e:
        logger.error(f"Error in check_for_matches: {e}")
    finally:
        conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, context)
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM approved_users WHERE user_id = ?', (update.effective_user.id,))
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
    finally:
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
        "به ربات خرید و فروش دارو خوش آمدید! لطفا یک گزینه را انتخاب کنید:",
        reply_markup=reply_markup
    )

async def admin_verify_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "لطفا کد تایید 5 رقمی ادمین را وارد کنید:",
        reply_markup=ReplyKeyboardRemove()
    )
    return States.ADMIN_VERIFICATION

async def admin_verify_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_code = update.message.text.strip()
    
    if user_code == ADMIN_SECRET_CODE:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # Check if already approved
            cursor.execute('SELECT user_id FROM approved_users WHERE user_id = ?', (update.effective_user.id,))
            if not cursor.fetchone():
                # Add to approved users
                cursor.execute('''
                INSERT INTO approved_users (user_id, verification_method)
                VALUES (?, ?)
                ''', (update.effective_user.id, 'admin_code'))
                
                # Update user verification status
                cursor.execute('''
                UPDATE users 
                SET is_verified = TRUE, verification_method = ?
                WHERE id = ?
                ''', ('admin_code', update.effective_user.id))
                
                conn.commit()
                
                await update.message.reply_text(
                    "✅ حساب شما با موفقیت تایید شد!\n\n"
                    "اکنون می‌توانید از تمام امکانات ربات استفاده کنید."
                )
                
                # Notify admin
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=f"کاربر @{update.effective_user.username} با کد ادمین تایید شد."
                    )
                except Exception as e:
                    logger.error(f"Failed to notify admin: {e}")
                
                return await start(update, context)
            else:
                await update.message.reply_text("حساب شما قبلا تایید شده است.")
                return ConversationHandler.END
                
        except Exception as e:
            logger.error(f"Error in admin verification: {e}")
            await update.message.reply_text("خطا در تایید حساب. لطفا دوباره تلاش کنید.")
            return ConversationHandler.END
        finally:
            conn.close()
    else:
        await update.message.reply_text("کد تایید نامعتبر است. لطفا دوباره تلاش کنید.")
        return States.ADMIN_VERIFICATION

async def upload_excel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("شما مجوز انجام این کار را ندارید.")
        return
    
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
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                INSERT OR REPLACE INTO admin_settings (id, excel_url, last_updated)
                VALUES (1, ?, CURRENT_TIMESTAMP)
                ''', (file_path,))
                conn.commit()
            except Exception as e:
                logger.error(f"Error saving excel info: {e}")
            finally:
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
                conn = get_db_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute('''
                    INSERT OR REPLACE INTO admin_settings (id, excel_url, last_updated)
                    VALUES (1, ?, CURRENT_TIMESTAMP)
                    ''', (github_url,))
                    conn.commit()
                except Exception as e:
                    logger.error(f"Error saving excel info: {e}")
                finally:
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

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Get all matching drugs from database (with highest price for each name)
        cursor.execute('''
        SELECT 
            f.id, 
            f.user_id,
            f.name,
            MAX(f.price) as price,
            f.date,
            SUM(f.quantity) as quantity,
            u.first_name || ' ' || COALESCE(u.last_name, '') AS seller_name
        FROM drug_items f
        JOIN users u ON f.user_id = u.id
        WHERE f.name LIKE ? AND f.quantity > 0
        GROUP BY f.name, f.user_id
        ORDER BY f.price DESC
        ''', (f'%{search_term}%',))
        results = cursor.fetchall()

        if results:
            context.user_data['search_results'] = [dict(row) for row in results]
            
            message = "نتایج جستجو (نمایش بالاترین قیمت برای هر دارو):\n\n"
            for idx, item in enumerate(results[:5]):
                message += (
                    f"{idx+1}. {item['name']} - قیمت: {item['price'] or 'نامشخص'}\n"
                    f"   فروشنده: {item['seller_name']}\n"
                    f"   موجودی: {item['quantity']}\n\n"
                )
            
            if len(results) > 5:
                message += f"➕ {len(results)-5} نتیجه دیگر...\n\n"
            
            sellers = {}
            for item in results:
                seller_id = item['user_id']
                if seller_id not in sellers:
                    sellers[seller_id] = {
                        'name': item['seller_name'],
                        'count': 0,
                        'items': []
                    }
                sellers[seller_id]['count'] += 1
                sellers[seller_id]['items'].append(dict(item))
            
            context.user_data['sellers'] = sellers
            
            keyboard = []
            for seller_id, seller_data in sellers.items():
                keyboard.append([InlineKeyboardButton(
                    f"فروشنده: {seller_data['name']} ({seller_data['count']} آیتم)", 
                    callback_data=f"seller_{seller_id}"
                )])
            
            keyboard.append([InlineKeyboardButton("لغو", callback_data="cancel")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                message + "لطفا فروشنده مورد نظر را انتخاب کنید:",
                reply_markup=reply_markup
            )
            return States.SELECT_SELLER
        else:
            await update.message.reply_text("هیچ دارویی با این نام یافت نشد.")
            return ConversationHandler.END
    except sqlite3.Error as e:
        logger.error(f"Database error in search: {e}")
        await update.message.reply_text("خطایی در پایگاه داده رخ داده است.")
        return ConversationHandler.END
    finally:
        conn.close()

async def select_seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await cancel(update, context)
        return

    if query.data.startswith("seller_"):
        seller_id = int(query.data.split("_")[1])
        sellers = context.user_data.get('sellers', {})
        seller_data = sellers.get(seller_id)
        
        if seller_data:
            context.user_data['selected_seller'] = {
                'id': seller_id,
                'name': seller_data['name']
            }
            context.user_data['seller_drugs'] = seller_data['items']
            context.user_data['selected_items'] = []
            
            # Get buyer's (current user) drugs
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                SELECT id, name, price, quantity 
                FROM drug_items 
                WHERE user_id = ? AND quantity > 0
                ''', (update.effective_user.id,))
                buyer_drugs = cursor.fetchall()
                context.user_data['buyer_drugs'] = [dict(row) for row in buyer_drugs]
                
                # Get seller's medical categories
                cursor.execute('''
                SELECT mc.id, mc.name 
                FROM user_categories uc
                JOIN medical_categories mc ON uc.category_id = mc.id
                WHERE uc.user_id = ?
                ''', (seller_id,))
                seller_categories = cursor.fetchall()
                context.user_data['seller_categories'] = [dict(row) for row in seller_categories]
                
            except Exception as e:
                logger.error(f"Error fetching data: {e}")
                context.user_data['buyer_drugs'] = []
                context.user_data['seller_categories'] = []
            finally:
                conn.close()
            
            return await show_two_column_selection(update, context)

async def show_two_column_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show the drug selection interface with proper v20+ syntax"""
    seller = context.user_data.get('selected_seller', {})
    seller_drugs = context.user_data.get('seller_drugs', [])
    buyer_drugs = context.user_data.get('buyer_drugs', [])
    selected_items = context.user_data.get('selected_items', [])
    
    # Create keyboard
    keyboard = []
    max_length = max(len(seller_drugs), len(buyer_drugs))
    
    for i in range(max_length):
        row = []
        # Seller drugs column
        if i < len(seller_drugs):
            drug = seller_drugs[i]
            is_selected = any(
                item['id'] == drug['id'] and item.get('type') == 'seller_drug'
                for item in selected_items
            )
            emoji = "✅ " if is_selected else ""
            row.append(InlineKeyboardButton(
                f"{emoji}💊 {drug['name'][:15]}", 
                callback_data=f"sellerdrug_{drug['id']}"
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
        InlineKeyboardButton("❌ لغو", callback_data="cancel")
    ])

    # Create message text
    message = (
        f"🔹 فروشنده: {seller.get('name', '')}\n\n"
        "💊 داروهای فروشنده | 📝 داروهای شما برای معامله\n\n"
        "علامت ✅ نشان‌دهنده انتخاب است\n"
        "پس از انتخاب موارد، روی «محاسبه جمع» کلیک کنید"
    )

    # Send or update message
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
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

    if query.data == "finish_selection":
        selected_items = context.user_data.get('selected_items', [])
        if not selected_items:
            await query.answer("لطفا حداقل یک مورد را انتخاب کنید", show_alert=True)
            return States.SELECT_ITEMS
        
        # Calculate totals
        seller_total = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in selected_items if item.get('type') == 'seller_drug'
        )
        
        buyer_total = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in selected_items if item.get('type') == 'buyer_drug'
        )
        
        difference = seller_total - buyer_total
        
        message = (
            "📊 جمع کل انتخاب‌ها:\n\n"
            f"💊 جمع داروهای فروشنده: {seller_total:,}\n"
            f"📝 جمع داروهای شما: {buyer_total:,}\n"
            f"💰 تفاوت: {abs(difference):,} ({'به نفع شما' if difference < 0 else 'به نفع فروشنده'})\n\n"
        )
        
        if difference != 0:
            message += "برای جبران تفاوت می‌توانید از دکمه زیر استفاده کنید:\n"
            keyboard = [
                [InlineKeyboardButton("➕ جبران تفاوت", callback_data="compensate")],
                [InlineKeyboardButton("✅ تایید نهایی", callback_data="confirm_totals")],
                [InlineKeyboardButton("✏️ ویرایش", callback_data="edit_selection")]
            ]
        else:
            message += "آیا مایل به ادامه هستید؟"
            keyboard = [
                [InlineKeyboardButton("✅ تایید نهایی", callback_data="confirm_totals")],
                [InlineKeyboardButton("✏️ ویرایش", callback_data="edit_selection")]
            ]
        
        await query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        return States.CONFIRM_TOTALS

    elif query.data == "compensate":
        difference = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in context.user_data['selected_items'] 
            if item.get('type') == 'seller_drug'
        ) - sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in context.user_data['selected_items'] 
            if item.get('type') == 'buyer_drug'
        )
        
        if difference > 0:  # Seller has more value, buyer needs to compensate
            selected_drug_ids = [
                item['id'] for item in context.user_data['selected_items'] 
                if item.get('type') == 'buyer_drug'
            ]
            
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                SELECT id, name, price, quantity 
                FROM drug_items 
                WHERE user_id = ? AND quantity > 0 AND id NOT IN ({})
                '''.format(','.join('?' * len(selected_drug_ids))), 
                [update.effective_user.id] + selected_drug_ids)
                
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
                
                await query.edit_message_text(
                    text=f"🔻 نیاز به جبران: {difference:,}\n\n"
                         f"لطفا از داروهای خود برای جبران تفاوت انتخاب کنید:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return States.COMPENSATION_SELECTION
                
            except Exception as e:
                logger.error(f"Error getting remaining drugs: {e}")
                await query.edit_message_text("خطا در دریافت داروها")
                return States.SELECT_ITEMS
            finally:
                conn.close()
                
        else:  # Buyer has more value, seller needs to compensate
            selected_drug_ids = [
                item['id'] for item in context.user_data['selected_items'] 
                if item.get('type') == 'seller_drug'
            ]
            
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                SELECT id, name, price, quantity 
                FROM drug_items 
                WHERE user_id = ? AND quantity > 0 AND id NOT IN ({})
                '''.format(','.join('?' * len(selected_drug_ids))), 
                [context.user_data['selected_seller']['id']] + selected_drug_ids)
                
                remaining_drugs = cursor.fetchall()
                
                if not remaining_drugs:
                    await query.answer("فروشنده داروی دیگری برای جبران ندارد!", show_alert=True)
                    return States.SELECT_ITEMS
                
                context.user_data['compensation'] = {
                    'difference': abs(difference),
                    'remaining_diff': abs(difference),
                    'selected_items': [],
                    'compensating_user': 'seller'
                }
                
                keyboard = []
                for drug in remaining_drugs:
                    keyboard.append([InlineKeyboardButton(
                        f"{drug['name']} ({drug['price']}) - موجودی: {drug['quantity']}", 
                        callback_data=f"comp_{drug['id']}"
                    )])
                
                await query.edit_message_text(
                    text=f"🔻 نیاز به جبران: {abs(difference):,}\n\n"
                         f"لطفا از داروهای فروشنده برای جبران تفاوت انتخاب کنید:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return States.COMPENSATION_SELECTION
                
            except Exception as e:
                logger.error(f"Error getting remaining drugs: {e}")
                await query.edit_message_text("خطا در دریافت داروها")
                return States.SELECT_ITEMS
            finally:
                conn.close()

    # Handle drug selection/deselection
    elif query.data.startswith(("sellerdrug_", "buyerdrug_")):
        item_type, item_id = query.data.split("_")
        item_id = int(item_id)
        
        selected_items = context.user_data.get('selected_items', [])
        
        # Toggle selection
        existing_idx = next(
            (i for i, item in enumerate(selected_items) 
             if item.get('id') == item_id and 
             ((item_type == "sellerdrug" and item.get('type') == 'seller_drug') or
              (item_type == "buyerdrug" and item.get('type') == 'buyer_drug'))
            ), None)
        
        if existing_idx is not None:
            selected_items.pop(existing_idx)
        else:
            # Find the item in available items
            if item_type == "sellerdrug":
                source = context.user_data.get('seller_drugs', [])
                item_type = 'seller_drug'
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
        seller_total = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in selected_items 
            if item.get('type') in ('seller_drug', 'seller_comp')
        )
        
        buyer_total = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in selected_items 
            if item.get('type') in ('buyer_drug', 'buyer_comp')
        )
        
        difference = seller_total - buyer_total
        
        message = (
            "📊 جمع کل پس از جبران:\n\n"
            f"💊 جمع داروهای فروشنده: {seller_total:,}\n"
            f"📝 جمع داروهای شما: {buyer_total:,}\n"
            f"💰 تفاوت نهایی: {abs(difference):,} ({'به نفع شما' if difference < 0 else 'به نفع فروشنده'})\n\n"
            "آیا مایل به ادامه هستید؟"
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ تایید نهایی", callback_data="confirm_totals")],
            [InlineKeyboardButton("✏️ ویرایش", callback_data="edit_selection")]
        ]
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard))
        return States.CONFIRM_TOTALS
    
    elif query.data.startswith("comp_"):  # Item selected
        item_id = int(query.data.split("_")[1])
        
        # Get item details
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT id, name, price, quantity 
            FROM drug_items 
            WHERE id = ?
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
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                
                if comp_data.get('compensating_user') == 'buyer':
                    cursor.execute('''
                    SELECT id, name, price, quantity 
                    FROM drug_items 
                    WHERE user_id = ? AND quantity > 0 AND id NOT IN ({})
                    '''.format(','.join('?' * len([i['id'] for i in comp_data['selected_items']]))), 
                    [update.effective_user.id] + [i['id'] for i in comp_data['selected_items']])
                else:
                    cursor.execute('''
                    SELECT id, name, price, quantity 
                    FROM drug_items 
                    WHERE user_id = ? AND quantity > 0 AND id NOT IN ({})
                    '''.format(','.join('?' * len([i['id'] for i in comp_data['selected_items']]))), 
                    [context.user_data['selected_seller']['id']] + [i['id'] for i in comp_data['selected_items']]

                    
                remaining_drugs = cursor.fetchall()
                
                if remaining_drugs:
                    keyboard = []
                    for drug in remaining_drugs:
                        keyboard.append([InlineKeyboardButton(
                            f"{drug['name']} ({drug['price']}) - موجودی: {drug['quantity']}", 
                            callback_data=f"comp_{drug['id']}"
                        )])
                    keyboard.append([InlineKeyboardButton("اتمام انتخاب", callback_data="comp_finish")])
                    
                    await update.message.reply_text(
                        "لطفا آیتم دیگری برای جبران انتخاب کنید:",
                        reply_markup=InlineKeyboardMarkup(keyboard))
                    return States.COMPENSATION_SELECTION
            
            except Exception as e:
                logger.error(f"Error showing remaining items: {e}")
            finally:
                conn.close()
        
        # If difference is covered or no more items
        keyboard = [[InlineKeyboardButton("اتمام انتخاب", callback_data="comp_finish")]]
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
        seller = context.user_data.get('selected_seller', {})
        buyer = update.effective_user
        
        if not selected_items or not seller:
            await query.edit_message_text("خطا در اطلاعات پیشنهاد. لطفا دوباره تلاش کنید.")
            return ConversationHandler.END
        
        conn = None
        try:
            # Calculate totals
            seller_total = sum(
                parse_price(item['price']) * item.get('selected_quantity', 1)
                for item in selected_items 
                if item.get('type') in ('seller_drug', 'seller_comp')
            )
            
            buyer_total = sum(
                parse_price(item['price']) * item.get('selected_quantity', 1)
                for item in selected_items 
                if item.get('type') in ('buyer_drug', 'buyer_comp')
            )
            
            difference = seller_total - buyer_total
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Insert offer
            cursor.execute('''
            INSERT INTO offers (seller_id, buyer_id, status, total_price)
            VALUES (?, ?, ?, ?)
            ''', (
                seller['id'],
                buyer.id,
                'pending',
                seller_total
            ))
            offer_id = cursor.lastrowid
            
            # Insert offer items
            for item in selected_items:
                if item['type'] in ('seller_drug', 'buyer_drug'):
                    cursor.execute('''
                    INSERT INTO offer_items (
                        offer_id, drug_name, price, quantity, item_type
                    ) VALUES (?, ?, ?, ?, ?)
                    ''', (
                        offer_id,
                        item['name'],
                        item['price'],
                        item.get('selected_quantity', 1),
                        'seller_drug' if item['type'] == 'seller_drug' else 'buyer_drug'
                    ))
                elif item['type'] in ('seller_comp', 'buyer_comp'):
                    cursor.execute('''
                    INSERT INTO compensation_items (
                        offer_id, drug_id, quantity
                    ) VALUES (?, ?, ?)
                    ''', (
                        offer_id,
                        item['id'],
                        item['selected_quantity']
                    ))
            
            conn.commit()
            
            # Prepare notification message for seller
            offer_message = f"📬 پیشنهاد جدید از {buyer.first_name}:\n\n"
            
            # Seller drugs
            seller_drugs = [
                item for item in selected_items 
                if item.get('type') == 'seller_drug'
            ]
            if seller_drugs:
                offer_message += "💊 داروهای درخواستی از شما:\n"
                for item in seller_drugs:
                    subtotal = parse_price(item['price']) * item.get('selected_quantity', 1)
                    offer_message += (
                        f"  • {item['name']}\n"
                        f"    تعداد: {item.get('selected_quantity', 1)}\n"
                        f"    قیمت واحد: {item['price']}\n"
                        f"    جمع: {subtotal:,}\n\n"
                    )
                offer_message += f"💰 جمع کل: {sum(parse_price(i['price'])*i.get('selected_quantity',1) for i in seller_drugs):,}\n\n"
            
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
                if item.get('type') in ('seller_comp', 'buyer_comp')
            ]
            if comp_items:
                offer_message += "➕ اقلام جبرانی:\n"
                for item in comp_items:
                    subtotal = parse_price(item['price']) * item.get('selected_quantity', 1)
                    offer_message += (
                        f"  • {item['name']} ({'از شما' if item['type'] == 'seller_comp' else 'از خریدار'})\n"
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
            
            # Send notification to seller
            try:
                await context.bot.send_message(
                    chat_id=seller['id'],
                    text=offer_message,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Failed to notify seller: {e}")
            
            # Prepare success message for buyer
            success_msg = "✅ پیشنهاد شما با موفقیت ارسال شد!\n\n"
            if seller_drugs:
                success_msg += f"💊 جمع داروهای فروشنده: {sum(parse_price(i['price'])*i.get('selected_quantity',1) for i in seller_drugs):,}\n"
            if buyer_drugs:
                success_msg += f"📝 جمع داروهای شما: {sum(parse_price(i['price'])*i.get('selected_quantity',1) for i in buyer_drugs):,}\n"
            if comp_items:
                success_msg += f"➕ جمع جبران: {sum(parse_price(i['price'])*i.get('selected_quantity',1) for i in comp_items):,}\n"
            success_msg += f"💵 تفاوت نهایی: {abs(difference):,}\n"
            success_msg += f"🆔 کد پیگیری: {offer_id}\n"
            
            await query.edit_message_text(success_msg)
            
        except sqlite3.Error as e:
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
        
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # Get offer details
            cursor.execute('''
            SELECT o.*, 
                   u.first_name || ' ' || COALESCE(u.last_name, '') AS buyer_name,
                   u.id AS buyer_id
            FROM offers o
            JOIN users u ON o.buyer_id = u.id
            WHERE o.id = ?
            ''', (offer_id,))
            offer = cursor.fetchone()
            
            if not offer:
                await query.edit_message_text("پیشنهاد یافت نشد")
                return
            
            if action == "reject":
                # Update offer status
                cursor.execute('''
                UPDATE offers SET status = 'rejected' WHERE id = ?
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
                UPDATE offers SET status = 'accepted' WHERE id = ?
                ''', (offer_id,))
                
                # Process drug items
                cursor.execute('''
                SELECT drug_name, price, quantity, item_type 
                FROM offer_items 
                WHERE offer_id = ?
                ''', (offer_id,))
                items = cursor.fetchall()
                
                for item in items:
                    if item['item_type'] == 'seller_drug':
                        # Deduct from seller's inventory
                        cursor.execute('''
                        UPDATE drug_items 
                        SET quantity = quantity - ?
                        WHERE user_id = ? AND name = ? AND price = ?
                        ''', (
                            item['quantity'],
                            offer['seller_id'],
                            item['drug_name'],
                            item['price']
                        ))
                    elif item['item_type'] == 'buyer_drug':
                        # Deduct from buyer's inventory
                        cursor.execute('''
                        UPDATE drug_items 
                        SET quantity = quantity - ?
                        WHERE user_id = ? AND name = ? AND price = ?
                        ''', (
                            item['quantity'],
                            offer['buyer_id'],
                            item['drug_name'],
                            item['price']
                        ))
                
                # Process compensation items
                cursor.execute('''
                SELECT ci.quantity, fi.name, fi.price, fi.user_id
                FROM compensation_items ci
                JOIN drug_items fi ON ci.drug_id = fi.id
                WHERE ci.offer_id = ?
                ''', (offer_id,))
                comp_items = cursor.fetchall()
                
                for item in comp_items:
                    # Deduct from owner's inventory
                    cursor.execute('''
                    UPDATE drug_items 
                    SET quantity = quantity - ?
                    WHERE id = ?
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
                
                seller_msg = (
                    f"✅ پیشنهاد با کد {offer_id} را پذیرفتید!\n\n"
                    "جزئیات معامله:\n"
                )
                
                # Add items to messages
                cursor.execute('''
                SELECT oi.drug_name, oi.price, oi.quantity, oi.item_type
                FROM offer_items oi
                WHERE oi.offer_id = ?
                ''', (offer_id,))
                items = cursor.fetchall()
                
                for item in items:
                    line = (
                        f"• {item['drug_name']} ({'از شما' if item['item_type'] == 'seller_drug' else 'از خریدار'})\n"
                        f"  تعداد: {item['quantity']}\n"
                        f"  قیمت: {item['price']}\n\n"
                    )
                    
                    if item['item_type'] == 'seller_drug':
                        buyer_msg += line
                    else:
                        seller_msg += line
                
                # Add compensation items
                cursor.execute('''
                SELECT fi.name, fi.price, ci.quantity
                FROM compensation_items ci
                JOIN drug_items fi ON ci.drug_id = fi.id
                WHERE ci.offer_id = ?
                ''', (offer_id,))
                comp_items = cursor.fetchall()
                
                if comp_items:
                    buyer_msg += "\n➕ اقلام جبرانی:\n"
                    seller_msg += "\n➕ اقلام جبرانی:\n"
                    
                    for item in comp_items:
                        line = (
                            f"• {item['name']}\n"
                            f"  تعداد: {item['quantity']}\n"
                            f"  قیمت: {item['price']}\n\n"
                        )
                        buyer_msg += line
                        seller_msg += line
                
                # Add contact info
                buyer_msg += f"\n✉️ تماس با فروشنده: @{offer['buyer_name']}"
                seller_msg += f"\n✉️ تماس با خریدار: @{offer['buyer_name']}"
                
                # Send notifications
                await context.bot.send_message(
                    chat_id=offer['buyer_id'],
                    text=buyer_msg
                )
                
                await context.bot.send_message(
                    chat_id=offer['seller_id'],
                    text=seller_msg
                )
                
                await query.edit_message_text("پیشنهاد با موفقیت پذیرفته شد!")
                return
                    
        except Exception as e:
            logger.error(f"Error handling offer response: {e}")
            await query.edit_message_text("خطا در پردازش پیشنهاد.")
        finally:
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
    keyboard.append([InlineKeyboardButton("لغو", callback_data="cancel")])

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
        
        await query.edit_message_text(
            f"✅ دارو انتخاب شده: {selected_drug[0]}\n"
            f"💰 قیمت: {selected_drug[1]}\n\n"
            "📅 لطفا تاریخ انقضا را وارد کنید (مثال: 1403/05/15):"
        )
        return States.ADD_DRUG_DATE
    
    except Exception as e:
        logger.error(f"Error in select_drug_for_adding: {e}")
        await query.edit_message_text("خطایی رخ داد. لطفا دوباره تلاش کنید.")
        return States.SEARCH_DRUG_FOR_ADDING

async def add_drug_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date = update.message.text
    if not re.match(r'^\d{4}/\d{2}/\d{2}$', date):
        await update.message.reply_text("فرمت تاریخ نامعتبر است. لطفا به صورت 1403/05/15 وارد کنید.")
        return States.ADD_DRUG_DATE
    
    context.user_data['drug_date'] = date
    await update.message.reply_text("لطفا تعداد یا مقدار موجود را وارد کنید:")
    return States.ADD_DRUG_QUANTITY

async def save_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید.")
            return States.ADD_DRUG_QUANTITY
        
        user = update.effective_user
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO drug_items (
            user_id, name, price, date, quantity
        ) VALUES (?, ?, ?, ?, ?)
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
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Get all available categories
        cursor.execute('SELECT id, name FROM medical_categories')
        all_categories = cursor.fetchall()
        
        # Get user's current categories
        cursor.execute('''
        SELECT mc.id, mc.name 
        FROM user_categories uc
        JOIN medical_categories mc ON uc.category_id = mc.id
        WHERE uc.user_id = ?
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
        
        keyboard.append([InlineKeyboardButton("ذخیره", callback_data="save_categories")])
        
        message = (
            "لطفا شاخه‌های دارویی مورد نظر خود را انتخاب کنید:\n\n"
            "علامت ✅ نشان‌دهنده انتخاب است\n"
            "پس از انتخاب، روی دکمه ذخیره کلیک کنید"
        )
        
        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        return States.SELECT_NEED_CATEGORY
        
    except Exception as e:
        logger.error(f"Error setting up categories: {e}")
        await update.message.reply_text("خطا در دریافت شاخه‌ها. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
    finally:
        conn.close()

async def toggle_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("togglecat_"):
        category_id = int(query.data.split("_")[1])
        
        if 'selected_categories' not in context.user_data:
            # Initialize with user's current categories
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                SELECT category_id 
                FROM user_categories 
                WHERE user_id = ?
                ''', (update.effective_user.id,))
                context.user_data['selected_categories'] = [row['category_id'] for row in cursor.fetchall()]
            except Exception as e:
                logger.error(f"Error getting user categories: {e}")
                context.user_data['selected_categories'] = []
            finally:
                conn.close()
        
        if category_id in context.user_data['selected_categories']:
            context.user_data['selected_categories'].remove(category_id)
        else:
            context.user_data['selected_categories'].append(category_id)
        
        # Refresh the category selection view
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
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
            
            keyboard.append([InlineKeyboardButton("ذخیره", callback_data="save_categories")])
            
            await query.edit_message_text(
                "لطفا شاخه‌های دارویی مورد نظر خود را انتخاب کنید:\n\n"
                "علامت ✅ نشان‌دهنده انتخاب است\n"
                "پس از انتخاب، روی دکمه ذخیره کلیک کنید",
                reply_markup=InlineKeyboardMarkup(keyboard))
            
        except Exception as e:
            logger.error(f"Error refreshing categories: {e}")
            await query.edit_message_text("خطا در بروزرسانی لیست. لطفا دوباره تلاش کنید.")
        finally:
            conn.close()

async def save_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if 'selected_categories' not in context.user_data:
        await query.edit_message_text("خطا در ذخیره‌سازی. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Clear existing categories
        cursor.execute('''
        DELETE FROM user_categories WHERE user_id = ?
        ''', (update.effective_user.id,))
        
        # Add selected categories
        for category_id in context.user_data['selected_categories']:
            cursor.execute('''
            INSERT INTO user_categories (user_id, category_id)
            VALUES (?, ?)
            ''', (update.effective_user.id, category_id))
        
        conn.commit()
        
        # Get category names for message
        cursor.execute('''
        SELECT name FROM medical_categories WHERE id IN ({})
        '''.format(','.join('?'*len(context.user_data['selected_categories']))),
        context.user_data['selected_categories'])
        
        category_names = [row['name'] for row in cursor.fetchall()]
        
        await query.edit_message_text(
            f"✅ شاخه‌های دارویی با موفقیت ذخیره شدند:\n\n"
            f"{', '.join(category_names)}"
        )
        
    except Exception as e:
        logger.error(f"Error saving categories: {e}")
        await query.edit_message_text("خطا در ذخیره‌سازی. لطفا دوباره تلاش کنید.")
    finally:
        conn.close()
    
    return ConversationHandler.END

async def list_my_drugs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, context)
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT name, price, date, quantity 
        FROM drug_items 
        WHERE user_id = ? AND quantity > 0
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
            
            await update.message.reply_text(message)
        else:
            await update.message.reply_text("شما هنوز هیچ دارویی اضافه نکرده‌اید.")
            
    except Exception as e:
        logger.error(f"Error listing drugs: {e}")
        await update.message.reply_text("خطا در دریافت لیست داروها. لطفا دوباره تلاش کنید.")
    finally:
        conn.close()

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
        
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO user_needs (
                user_id, name, description, quantity
            ) VALUES (?, ?, ?, ?)
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
            conn.close()
        
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("لطفا یک عدد صحیح وارد کنید.")
        return States.ADD_NEED_QUANTITY

async def list_my_needs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, context)
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT id, name, description, quantity 
        FROM user_needs 
        WHERE user_id = ?
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
            
            await update.message.reply_text(message)
        else:
            await update.message.reply_text("شما هنوز هیچ نیازی ثبت نکرده‌اید.")
            
    except Exception as e:
        logger.error(f"Error listing needs: {e}")
        await update.message.reply_text("خطا در دریافت لیست نیازها. لطفا دوباره تلاش کنید.")
    finally:
        conn.close()

async def handle_match_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("view_match_"):
        parts = query.data.split("_")
        drug_id = int(parts[2])
        need_id = int(parts[3])
        
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # Get drug details
            cursor.execute('''
            SELECT f.*, 
                   u.first_name || ' ' || COALESCE(u.last_name, '') AS seller_name
            FROM drug_items f
            JOIN users u ON f.user_id = u.id
            WHERE f.id = ?
            ''', (drug_id,))
            drug = cursor.fetchone()
            
            if not drug:
                await query.edit_message_text("دارو یافت نشد.")
                return
            
            # Get need details
            cursor.execute('''
            SELECT * FROM user_needs WHERE id = ?
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
                f"فروشنده: {drug['seller_name']}\n\n"
                "آیا مایل به خرید این دارو هستید؟"
            )
            
            keyboard = [
                [InlineKeyboardButton("خرید این دارو", callback_data=f"buy_match_{drug_id}")],
                [InlineKeyboardButton("لغو", callback_data="cancel")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            
            # Store drug and need in context for purchase flow
            context.user_data['matched_drug'] = dict(drug)
            context.user_data['matched_need'] = dict(need)
            
        except Exception as e:
            logger.error(f"Error handling match view: {e}")
            await query.edit_message_text("خطا در نمایش اطلاعات تطابق.")
        finally:
            conn.close()

async def handle_match_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("buy_match_"):
        drug_id = int(query.data.split("_")[2])
        drug = context.user_data.get('matched_drug')
        need = context.user_data.get('matched_need')
        
        if not drug or not need:
            await query.edit_message_text("خطا در اطلاعات خرید. لطفا دوباره تلاش کنید.")
            return
        
        # Set up the purchase flow similar to regular search
        context.user_data['selected_seller'] = {
            'id': drug['user_id'],
            'name': drug['seller_name']
        }
        
        # Get seller's drugs (just the matched one)
        context.user_data['seller_drugs'] = [{
            'id': drug['id'],
            'user_id': drug['user_id'],
            'name': drug['name'],
            'price': drug['price'],
            'date': drug['date'],
            'quantity': drug['quantity']
        }]
        
        # Get buyer's drugs
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT id, name, price, quantity 
            FROM drug_items 
            WHERE user_id = ? AND quantity > 0
            ''', (update.effective_user.id,))
            buyer_drugs = cursor.fetchall()
            context.user_data['buyer_drugs'] = [dict(row) for row in buyer_drugs]
            
            # Get seller's categories
            cursor.execute('''
            SELECT mc.id, mc.name 
            FROM user_categories uc
            JOIN medical_categories mc ON uc.category_id = mc.id
            WHERE uc.user_id = ?
            ''', (drug['user_id'],))
            seller_categories = cursor.fetchall()
            context.user_data['seller_categories'] = [dict(row) for row in seller_categories]
            
        except Exception as e:
            logger.error(f"Error fetching data for purchase: {e}")
            context.user_data['buyer_drugs'] = []
            context.user_data['seller_categories'] = []
        finally:
            conn.close()
        
        # Auto-select the matched drug
        context.user_data['selected_items'] = [{
            'id': drug['id'],
            'name': drug['name'],
            'price': drug['price'],
            'quantity': drug['quantity'],
            'type': 'seller_drug',
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
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO user_registrations (
                user_id, pharmacy_name, founder_name, national_card_image,
                license_image, medical_card_image, phone, status, admin_username
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                update.effective_user.id,
                context.user_data['pharmacy_name'],
                context.user_data['founder_name'],
                context.user_data['national_card_image'],
                context.user_data['license_image'],
                context.user_data['medical_card_image'],
                context.user_data['phone'],
                'pending',
                context.bot.username
            ))
            conn.commit()
            
            await update.message.reply_text(
                "✅ اطلاعات شما با موفقیت ثبت شد!\n\n"
                "در حال حاضر حساب شما در انتظار تایید مدیریت است. پس از تایید می‌توانید از ربات استفاده کنید."
            )
            
            # Notify admin
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"📝 درخواست ثبت نام جدید:\n\n"
                         f"🔹 کاربر: @{update.effective_user.username}\n"
                         f"🔹 داروخانه: {context.user_data['pharmacy_name']}\n"
                         f"🔹 مسئول: {context.user_data['founder_name']}\n\n"
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
            conn.close()
        
        return ConversationHandler.END
    else:
        await update.message.reply_text("کد تایید نامعتبر است. لطفا دوباره تلاش کنید.")
        return States.VERIFICATION_CODE

async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لطفا شماره تلفن همراه را وارد کنید:")
    return States.REGISTER_PHONE

async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("شما مجوز انجام این کار را ندارید.")
        return
    
    parts = update.message.text.split('_')
    if len(parts) != 2:
        await update.message.reply_text("فرمت دستور نامعتبر است.")
        return
    
    user_id = int(parts[1])
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Check if already approved
        cursor.execute('SELECT user_id FROM approved_users WHERE user_id = ?', (user_id,))
        if cursor.fetchone():
            await update.message.reply_text("این کاربر قبلا تایید شده است.")
            return
        
        # Approve user
        cursor.execute('INSERT INTO approved_users (user_id) VALUES (?)', (user_id,))
        
        # Update registration status
        cursor.execute('''
        UPDATE user_registrations 
        SET status = 'approved' 
        WHERE user_id = ?
        ''', (user_id,))
        
        conn.commit()
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ حساب شما توسط مدیریت تایید شد!\n\n"
                     "اکنون می‌توانید از تمام امکانات ربات استفاده کنید."
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        
        await update.message.reply_text(f"کاربر با شناسه {user_id} تایید شد.")
        
    except Exception as e:
        logger.error(f"Error approving user: {e}")
        await update.message.reply_text("خطا در تایید کاربر.")
    finally:
        conn.close()

async def reject_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("شما مجوز انجام این کار را ندارید.")
        return
    
    parts = update.message.text.split('_')
    if len(parts) != 2:
        await update.message.reply_text("فرمت دستور نامعتبر است.")
        return
    
    user_id = int(parts[1])
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Update registration status
        cursor.execute('''
        UPDATE user_registrations 
        SET status = 'rejected' 
        WHERE user_id = ?
        ''', (user_id,))
        
        conn.commit()
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ درخواست ثبت نام شما رد شد.\n\n"
                     "لطفا برای اطلاعات بیشتر با پشتیبانی تماس بگیرید."
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        
        await update.message.reply_text(f"کاربر با شناسه {user_id} رد شد.")
        
    except Exception as e:
        logger.error(f"Error rejecting user: {e}")
        await update.message.reply_text("خطا در رد کاربر.")
    finally:
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
        elif isinstance(context.error, sqlite3.Error):
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
            States.SELECT_SELLER: [CallbackQueryHandler(select_seller)],
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

    # Add all handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list", list_my_drugs))
    application.add_handler(trade_conv)
    application.add_handler(add_drug_conv)
    application.add_handler(categories_conv)
    application.add_handler(need_conv)
    application.add_handler(registration_conv)
    application.add_handler(verification_conv)
    application.add_handler(admin_verify_conv)
    application.add_handler(admin_excel_conv)
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
