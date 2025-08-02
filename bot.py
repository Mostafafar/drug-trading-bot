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
    error
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
    ExtBot
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
    'password': 'm13821382',
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
    REGISTER_ADDRESS = auto()
    REGISTER_LOCATION = auto()
    VERIFICATION_CODE = auto()
    ADMIN_VERIFICATION = auto()
    SIMPLE_VERIFICATION = auto()
    SEARCH_DRUG = auto()
    SELECT_PHARMACY = auto()
    SELECT_ITEMS = auto()
    SELECT_QUANTITY = auto()
    CONFIRM_OFFER = auto()
    CONFIRM_TOTALS = auto()
    SELECT_NEED_CATEGORY = auto()
    ADD_NEED_NAME = auto()
    ADD_NEED_DESC = auto()
    ADD_NEED_QUANTITY = auto()
    SEARCH_DRUG_FOR_NEED = auto()
    SELECT_DRUG_FOR_NEED = auto()
    COMPENSATION_SELECTION = auto()
    COMPENSATION_QUANTITY = auto()
    ADD_DRUG_DATE = auto()
    ADD_DRUG_QUANTITY = auto()
    SEARCH_DRUG_FOR_ADDING = auto()
    SELECT_DRUG_FOR_ADDING = auto()
    ADMIN_UPLOAD_EXCEL = auto()
    EDIT_ITEM = auto()
    EDIT_DRUG = auto()
    EDIT_NEED = auto()

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
            return conn  # این return باید داخل تابع باشد
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
                simple_code TEXT
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
                location_lat DOUBLE PRECISION,
                location_lng DOUBLE PRECISION,
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
            
            # Simple codes table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS simple_codes (
                code TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_by BIGINT[] DEFAULT array[]::BIGINT[],
                max_uses INTEGER DEFAULT 5
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
    """Parse price string into float"""
    if not price_str:
        return 0
    try:
        return float(str(price_str).replace(',', ''))
    except ValueError:
        return 0

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
    """Start command handler"""
    try:
        await ensure_user(update, context)
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Check if user is verified
                cursor.execute('''
                SELECT is_verified FROM users WHERE id = %s
                ''', (update.effective_user.id,))
                result = cursor.fetchone()
                
                if not result or not result[0]:
                    # User not verified - show registration options
                    keyboard = [
                        [InlineKeyboardButton("ثبت نام با کد ادمین", callback_data="admin_verify")],
                        [InlineKeyboardButton("ثبت نام با مدارک", callback_data="register")],
                        [InlineKeyboardButton("ورود با کد ساده", callback_data="simple_verify")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    try:
                        await update.message.reply_text(
                            "برای استفاده از ربات باید ثبت نام کنید. لطفا روش ثبت نام را انتخاب کنید:",
                            reply_markup=reply_markup
                        )
                    except Exception as e:
                        logger.error(f"Error sending start message: {e}")
                        return States.START
                    
                    return States.START
        except Exception as e:
            logger.error(f"Error checking verification status: {e}")
        finally:
            if conn:
                conn.close()
        
        # User is verified - show main menu
        context.application.create_task(check_for_matches(update.effective_user.id, context))
        
        keyboard = [
            ['اضافه کردن دارو', 'جستجوی دارو'],
            ['تنظیم شاخه‌های دارویی', 'لیست داروهای من'],
            ['ثبت نیاز جدید', 'لیست نیازهای من']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        try:
            await update.message.reply_text(
                "به ربات تبادل دارو خوش آمدید! لطفا یک گزینه را انتخاب کنید:",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error sending main menu: {e}")
        
        return ConversationHandler.END
    
    except Exception as e:
        logger.error(f"Error in start handler: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
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
        elif query.data == "edit_drugs":
            return await edit_drugs(update, context)
        elif query.data.startswith("edit_drug_"):
            return await edit_drug_item(update, context)
        elif query.data in ["edit_name", "edit_price", "edit_date", "edit_quantity", "delete_drug"]:
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
        elif query.data.startswith("view_match_"):
            return await handle_match_notification(update, context)
        
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
        # Try to notify user if possible
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
                SELECT code, used_by, max_uses 
                FROM simple_codes 
                WHERE code = %s AND array_length(used_by, 1) < max_uses
                ''', (user_code,))
                result = cursor.fetchone()
                
                if result:
                    code, used_by, max_uses = result
                    used_by = used_by or []
                    
                    # Check if user already used this code
                    if update.effective_user.id in used_by:
                        await update.message.reply_text(
                            "شما قبلاً با این کد ثبت نام کرده‌اید."
                        )
                        return ConversationHandler.END
                    
                    # Update the used_by array
                    cursor.execute('''
                    UPDATE simple_codes 
                    SET used_by = array_append(used_by, %s)
                    WHERE code = %s
                    ''', (update.effective_user.id, user_code))
                    
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
        
        try:
            await query.edit_message_text(
                "لطفا کد تایید داروخانه را وارد کنید:",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="لطفا کد تایید داروخانه را وارد کنید:",
                reply_markup=ReplyKeyboardRemove()
            )
        return States.ADMIN_VERIFICATION
    except Exception as e:
        logger.error(f"Error in admin_verify_start: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def admin_verify_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify admin code for pharmacy registration"""
    try:
        user_code = update.message.text.strip()
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Check if code is valid and pharmacy is verified
                cursor.execute('''
                SELECT user_id FROM pharmacies 
                WHERE admin_code = %s AND verified = TRUE
                ''', (user_code,))
                result = cursor.fetchone()
                
                if result:
                    pharmacy_id = result[0]
                    
                    # Check if user already registered as pharmacy
                    cursor.execute('''
                SELECT 1 FROM pharmacies WHERE user_id = %s
                ''', (update.effective_user.id,))
                    if cursor.fetchone():
                        await update.message.reply_text(
                            "شما قبلاً با یک داروخانه ثبت نام کرده‌اید."
                        )
                        return ConversationHandler.END
                    
                    # Register user with admin code
                    cursor.execute('''
                    INSERT INTO users (id, first_name, last_name, username, is_verified, verification_method)
                    VALUES (%s, %s, %s, %s, TRUE, 'admin_code')
                    ON CONFLICT (id) DO UPDATE SET
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        username = EXCLUDED.username,
                        is_verified = TRUE,
                        verification_method = 'admin_code'
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
    except Exception as e:
        logger.error(f"Error in admin_verify_code: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

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

async def register_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get location in registration process"""
    try:
        address = update.message.text
        context.user_data['address'] = address
        
        keyboard = [[KeyboardButton("اشتراک گذاری موقعیت مکانی", request_location=True)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            "لطفا موقعیت مکانی داروخانه را با استفاده از دکمه زیر ارسال کنید:",
            reply_markup=reply_markup
        )
        return States.REGISTER_LOCATION
    except Exception as e:
        logger.error(f"Error in register_location: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def verify_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify registration code"""
    try:
        location = update.message.location
        context.user_data['location_lat'] = location.latitude
        context.user_data['location_lng'] = location.longitude
        
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
                        location_lat, location_lng, verified
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        update.effective_user.id,
                        context.user_data.get('pharmacy_name'),
                        context.user_data.get('founder_name'),
                        context.user_data.get('national_card'),
                        context.user_data.get('license'),
                        context.user_data.get('medical_card'),
                        context.user_data.get('phone'),
                        context.user_data.get('address'),
                        context.user_data.get('location_lat'),
                        context.user_data.get('location_lng'),
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
    """Handle Excel file upload from admin"""
    try:
        if update.message.document:
            # Handle document upload
            file = await context.bot.get_file(update.message.document.file_id)
            file_path = await download_file(file, "drug_prices", "admin")
            
            try:
                # Process Excel file
                df = pd.read_excel(file_path, engine='openpyxl')
                df = df.drop(columns=[col for col in df.columns if 'Unnamed' in col])
                drug_list = df[['name', 'price']].dropna().drop_duplicates().values.tolist()
                drug_list = [(str(name).strip(), str(price).strip()) for name, price in drug_list if str(name).strip()]
                
                # Save to local file
                df.to_excel(excel_file, index=False, engine='openpyxl')
                
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
                    excel_data = BytesIO(response.content)
                    df = pd.read_excel(excel_data, engine='openpyxl')
                    df = df.drop(columns=[col for col in df.columns if 'Unnamed' in col])
                    drug_list = df[['name', 'price']].dropna().drop_duplicates().values.tolist()
                    drug_list = [(str(name).strip(), str(price).strip()) for name, price in drug_list if str(name).strip()]
                    
                    df.to_excel(excel_file, index=False, engine='openpyxl')
                    
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
    """Toggle medical category selection for user"""
    try:
        query = update.callback_query
        await query.answer()
        
        if not query.data.startswith("togglecat_"):
            return
            
        category_id = int(query.data.split("_")[1])
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Check if user already has this category
                cursor.execute('''
                SELECT 1 FROM user_categories 
                WHERE user_id = %s AND category_id = %s
                ''', (update.effective_user.id, category_id))
                
                if cursor.fetchone():
                    # Remove category
                    cursor.execute('''
                    DELETE FROM user_categories 
                    WHERE user_id = %s AND category_id = %s
                    ''', (update.effective_user.id, category_id))
                    action = "حذف شد"
                else:
                    # Add category
                    cursor.execute('''
                    INSERT INTO user_categories (user_id, category_id)
                    VALUES (%s, %s)
                    ''', (update.effective_user.id, category_id))
                    action = "اضافه شد"
                
                conn.commit()
                
                # Get updated category list
                cursor.execute('''
                SELECT mc.id, mc.name, 
                       EXISTS(SELECT 1 FROM user_categories uc 
                              WHERE uc.user_id = %s AND uc.category_id = mc.id) as selected
                FROM medical_categories mc
                ORDER BY mc.name
                ''', (update.effective_user.id,))
                categories = cursor.fetchall()
                
                # Rebuild keyboard
                keyboard = []
                for cat in categories:
                    emoji = "✅ " if cat['selected'] else "◻️ "
                    keyboard.append([InlineKeyboardButton(
                        f"{emoji}{cat['name']}", 
                        callback_data=f"togglecat_{cat['id']}"
                    )])
                
                keyboard.append([InlineKeyboardButton("💾 ذخیره", callback_data="save_categories")])
                
                await query.edit_message_reply_markup(
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
        except Exception as e:
            logger.error(f"Error toggling category: {e}")
            await query.answer("خطا در تغییر وضعیت دسته‌بندی", show_alert=True)
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in toggle_category: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")

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
    """Setup medical categories for user"""
    try:
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                # Get all categories and user's selected categories
                cursor.execute('''
                SELECT mc.id, mc.name, 
                       EXISTS(SELECT 1 FROM user_categories uc 
                              WHERE uc.user_id = %s AND uc.category_id = mc.id) as selected
                FROM medical_categories mc
                ORDER BY mc.name
                ''', (update.effective_user.id,))
                categories = cursor.fetchall()
                
                if not categories:
                    await update.message.reply_text("هیچ شاخه دارویی تعریف نشده است.")
                    return
                
                # Build keyboard
                keyboard = []
                for cat in categories:
                    emoji = "✅ " if cat['selected'] else "◻️ "
                    keyboard.append([InlineKeyboardButton(
                        f"{emoji}{cat['name']}", 
                        callback_data=f"togglecat_{cat['id']}"
                    )])
                
                keyboard.append([InlineKeyboardButton("💾 ذخیره", callback_data="save_categories")])
                
                await update.message.reply_text(
                    "لطفا شاخه‌های دارویی مورد نظر خود را انتخاب کنید:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
        except Exception as e:
            logger.error(f"Error setting up categories: {e}")
            await update.message.reply_text("خطا در دریافت لیست شاخه‌های دارویی.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in setup_medical_categories: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")

# Drug Management
async def add_drug_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start process to add a drug item"""
    try:
        await ensure_user(update, context)
        await update.message.reply_text(
            "لطفا نام دارویی که می‌خواهید اضافه کنید را جستجو کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return States.SEARCH_DRUG_FOR_ADDING
    except Exception as e:
        logger.error(f"Error in add_drug_item: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
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
        keyboard = []
        try:
            for idx, (name, price) in enumerate(matched_drugs[:10]):  # Limit to 10 results
                display_text = f"{name[:20]}... ({price})" if len(name) > 20 else f"{name} ({price})"
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

async def verify_database():
    """Verify database connection and structure"""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Check if drug_items table exists and has records
            cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'drug_items'
            )
            """)
            table_exists = cursor.fetchone()[0]
            
            if not table_exists:
                logger.error("drug_items table does not exist!")
                return False
                
            cursor.execute("SELECT COUNT(*) FROM drug_items")
            count = cursor.fetchone()[0]
            logger.info(f"Found {count} records in drug_items table")
            
            return True
            
    except Exception as e:
        logger.error(f"Database verification failed: {e}")
        return False
    finally:
        if conn:
            conn.close()

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
    try:
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
                    return States.EDIT_DRUG
                else:
                    await update.message.reply_text("شما هنوز هیچ دارویی اضافه نکرده‌اید.")
                    
        except Exception as e:
            logger.error(f"Error listing drugs: {e}")
            await update.message.reply_text("خطا در دریافت لیست داروها. لطفا دوباره تلاش کنید.")
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in list_my_drugs: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
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
                
                keyboard = []
                for drug in drugs:
                    keyboard.append([InlineKeyboardButton(
                        f"{drug['name'][:20]}... ({drug['quantity']})" if len(drug['name']) > 20 else f"{drug['name']} ({drug['quantity']})",
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
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_list")]
            ]
            
            await query.edit_message_text(
                f"ویرایش دارو:\n\n"
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
                    
                    await query.edit_message_text(
                        f"✅ داروی {drug['name']} با موفقیت حذف شد.")
                    
                    # Return to drugs list
                    return await list_my_drugs(update, context)
                    
            except Exception as e:
                logger.error(f"Database error during deletion: {e}")
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
        except:
            await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
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
                        f"{need['name'][:20]}... ({need['quantity']})" if len(need['name']) > 20 else f"{need['name']} ({need['quantity']})",
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
    """Handle drug search requests and display results"""
    try:
        search_term = update.message.text.strip().lower()
        context.user_data['search_term'] = search_term

        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                # Search for drugs with similarity matching
                cursor.execute('''
                SELECT 
                    di.id, di.user_id, di.name, di.price, di.date, di.quantity,
                    p.name AS pharmacy_name,
                    similarity(di.name, %s) AS match_score
                FROM drug_items di
                JOIN pharmacies p ON di.user_id = p.user_id
                WHERE 
                    di.quantity > 0 AND
                    p.verified = TRUE AND
                    (di.name ILIKE %s OR similarity(di.name, %s) > 0.3)
                ORDER BY match_score DESC, di.price DESC
                LIMIT 20
                ''', (search_term, f'%{search_term}%', search_term))
                
                results = cursor.fetchall()
                logger.info(f"Found {len(results)} matching drugs")

                if results:
                    context.user_data['search_results'] = [dict(row) for row in results]
                    
                    # Group results by pharmacy
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
                    
                    # Create keyboard with pharmacy options
                    keyboard = []
                    for pharmacy_id, pharmacy_data in pharmacies.items():
                        keyboard.append([InlineKeyboardButton(
                            f"🏥 {pharmacy_data['name']} ({pharmacy_data['count']} دارو)", 
                            callback_data=f"pharmacy_{pharmacy_id}"
                        )])
                    
                    keyboard.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back")])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    # Prepare message with search results
                    message = "🔍 نتایج جستجو:\n\n"
                    for idx, item in enumerate(results[:5]):  # Show first 5 results
                        message += (
                            f"🏥 داروخانه: {item['pharmacy_name']}\n"
                            f"💊 دارو: {item['name']}\n"
                            f"💰 قیمت: {item['price'] or 'نامشخص'}\n"
                            f"📅 تاریخ انقضا: {item['date']}\n"
                            f"📦 موجودی: {item['quantity']}\n\n"
                        )
                    
                    if len(results) > 5:
                        message += f"\n➕ {len(results)-5} نتیجه دیگر...\n\n"
                    
                    message += "لطفا داروخانه مورد نظر را انتخاب کنید:"
                    
                    await update.message.reply_text(
                        message,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return States.SELECT_PHARMACY
                else:
                    # No results found
                    keyboard = [
                        [InlineKeyboardButton("🔙 بازگشت به جستجو", callback_data="back_to_search")],
                        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="back")]
                    ]
                    
                    await update.message.reply_text(
                        "هیچ دارویی با این نام یافت نشد.\n\n"
                        "می‌توانید دوباره جستجو کنید یا به منوی اصلی بازگردید.",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    return States.SEARCH_DRUG

        except psycopg2.Error as e:
            logger.error(f"Database error in search: {str(e)}")
            await update.message.reply_text(
                "خطایی در پایگاه داده رخ داده است. لطفاً بعداً دوباره تلاش کنید.",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Unexpected error in search: {str(e)}")
            await update.message.reply_text(
                "خطای غیرمنتظره‌ای رخ داده است. لطفاً با پشتیبانی تماس بگیرید.",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
            
        finally:
            if conn:
                conn.close()

    except Exception as e:
        logger.error(f"Error in handle_search: {str(e)}")
        await update.message.reply_text(
            "خطایی در پردازش درخواست شما رخ داد. لطفاً دوباره تلاش کنید.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END 
async def debug_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug command to check database status"""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Check drug_items table
            cursor.execute("SELECT COUNT(*) FROM drug_items")
            drug_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT * FROM drug_items LIMIT 5")
            sample_drugs = cursor.fetchall()
            
            message = (
                f"Database Status:\n"
                f"Drug items count: {drug_count}\n"
                f"Sample drugs:\n"
            )
            
            for drug in sample_drugs:
                message += f"- {drug[2]} (Qty: {drug[5]})\n"
                
            await update.message.reply_text(message)
            
    except Exception as e:
        await update.message.reply_text(f"Database error: {str(e)}")
    finally:
        if conn:
            conn.close()

# Add to your main() function:
application.add_handler(CommandHandler("debug", debug_db))

async def select_pharmacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Select pharmacy from search results"""
    try:
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
                
                conn = None
                try:
                    conn = get_db_connection()
                    with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                        # Get buyer's drugs for potential exchange
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
    except Exception as e:
        logger.error(f"Error in select_pharmacy: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END
async def add_drug_from_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    drug_name = query.data.replace("add_drug_", "")
    context.user_data['selected_drug'] = {'name': drug_name, 'price': ''}
    
    await query.edit_message_text(
        f"در حال ثبت داروی جدید: {drug_name}\n\n"
        "لطفا قیمت دارو را وارد کنید:"
    )
    return States.ADD_DRUG_PRICE

async def show_two_column_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show two-column selection interface for drugs"""
    try:
        pharmacy = context.user_data.get('selected_pharmacy', {})
        pharmacy_drugs = context.user_data.get('pharmacy_drugs', [])
        buyer_drugs = context.user_data.get('buyer_drugs', [])
        selected_items = context.user_data.get('selected_items', [])
        
        keyboard = []
        max_length = max(len(pharmacy_drugs), len(buyer_drugs))
        
        for i in range(max_length):
            row = []
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

        keyboard.append([
            InlineKeyboardButton("💰 محاسبه جمع", callback_data="finish_selection"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_pharmacies"),
            InlineKeyboardButton("❌ لغو", callback_data="cancel")
        ])

        message = (
            f"🔹 داروخانه: {pharmacy.get('name', '')}\n\n"
            "💊 داروهای داروخانه | 📝 داروهای شما برای تبادل\n\n"
            "علامت ✅ نشان‌دهنده انتخاب است\n"
            "پس از انتخاب موارد، روی «محاسبه جمع» کلیک کنید"
        )

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
    except Exception as e:
        logger.error(f"Error in show_two_column_selection: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def select_items(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle item selection in two-column interface"""
    try:
        query = update.callback_query
        await query.answer()

        if query.data == "cancel":
            await cancel(update, context)
            return ConversationHandler.END

        if query.data == "back_to_pharmacies":
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
                message,
                reply_markup=InlineKeyboardMarkup(keyboard))
            return States.CONFIRM_TOTALS

        elif query.data.startswith(("pharmacydrug_", "buyerdrug_")):
            item_type, item_id = query.data.split("_")
            item_id = int(item_id)
            
            selected_items = context.user_data.get('selected_items', [])
            
            # Check if item already selected
            existing_idx = next(
                (i for i, item in enumerate(selected_items) 
                 if item.get('id') == item_id and 
                 ((item_type == "pharmacydrug" and item.get('type') == 'pharmacy_drug') or
                  (item_type == "buyerdrug" and item.get('type') =='buyer_drug'))),
                None
            )
            
            if existing_idx is not None:
                # Remove from selected items
                selected_items.pop(existing_idx)
            else:
                # Add to selected items
                if item_type == "pharmacydrug":
                    pharmacy_drugs = context.user_data.get('pharmacy_drugs', [])
                    drug = next((d for d in pharmacy_drugs if d['id'] == item_id), None)
                    if drug:
                        selected_items.append({
                            'id': drug['id'],
                            'name': drug['name'],
                            'price': drug['price'],
                            'quantity': drug['quantity'],
                            'type': 'pharmacy_drug',
                            'selected_quantity': 1
                        })
                else:
                    buyer_drugs = context.user_data.get('buyer_drugs', [])
                    drug = next((d for d in buyer_drugs if d['id'] == item_id), None)
                    if drug:
                        selected_items.append({
                            'id': drug['id'],
                            'name': drug['name'],
                            'price': drug['price'],
                            'quantity': drug['quantity'],
                            'type': 'buyer_drug',
                            'selected_quantity': 1
                        })
            
            context.user_data['selected_items'] = selected_items
            return await show_two_column_selection(update, context)
            
    except Exception as e:
        logger.error(f"Error in select_items: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def handle_compensation_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle compensation selection for trade difference"""
    try:
        query = update.callback_query
        await query.answer()

        selected_items = context.user_data.get('selected_items', [])
        
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
        
        # Get buyer's drugs for compensation
        buyer_drugs = context.user_data.get('buyer_drugs', [])
        
        if not buyer_drugs:
            await query.answer("هیچ دارویی برای جبران تفاوت ندارید", show_alert=True)
            return States.CONFIRM_TOTALS
        
        keyboard = []
        for drug in buyer_drugs:
            # Skip drugs already selected for trade
            if any(item['id'] == drug['id'] and item.get('type') == 'buyer_drug' 
                   for item in selected_items):
                continue
                
            keyboard.append([InlineKeyboardButton(
                f"{drug['name']} ({drug['price']})", 
                callback_data=f"comp_{drug['id']}"
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_totals")])
        
        await query.edit_message_text(
            f"تفاوت مبلغ: {abs(difference):,}\n\n"
            "لطفا دارویی برای جبران تفاوت انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.COMPENSATION_SELECTION
    except Exception as e:
        logger.error(f"Error in handle_compensation_selection: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def handle_compensation_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle compensation quantity selection"""
    try:
        query = update.callback_query
        await query.answer()

        if query.data.startswith("comp_"):
            drug_id = int(query.data.split("_")[1])
            buyer_drugs = context.user_data.get('buyer_drugs', [])
            drug = next((d for d in buyer_drugs if d['id'] == drug_id), None)
            
            if not drug:
                await query.answer("دارو یافت نشد", show_alert=True)
                return States.COMPENSATION_SELECTION
                
            context.user_data['compensation_drug'] = drug
            
            await query.edit_message_text(
                f"داروی انتخابی: {drug['name']}\n"
                f"قیمت واحد: {drug['price']}\n\n"
                "لطفا تعداد مورد نیاز برای جبران تفاوت را وارد کنید:"
            )
            return States.COMPENSATION_QUANTITY
    except Exception as e:
        logger.error(f"Error in handle_compensation_quantity: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def save_compensation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save compensation selection"""
    try:
        try:
            quantity = int(update.message.text)
            if quantity <= 0:
                await update.message.reply_text("لطفا عددی بزرگتر از صفر وارد کنید.")
                return States.COMPENSATION_QUANTITY
                
            drug = context.user_data.get('compensation_drug')
            if not drug:
                await update.message.reply_text("خطا در پردازش. لطفا دوباره تلاش کنید.")
                return ConversationHandler.END
                
            selected_items = context.user_data.get('selected_items', [])
            selected_items.append({
                'id': drug['id'],
                'name': drug['name'],
                'price': drug['price'],
                'quantity': drug['quantity'],
                'type': 'compensation',
                'selected_quantity': quantity
            })
            context.user_data['selected_items'] = selected_items
            
            return await confirm_totals(update, context)
            
        except ValueError:
            await update.message.reply_text("لطفا یک عدد صحیح وارد کنید.")
            return States.COMPENSATION_QUANTITY
    except Exception as e:
        logger.error(f"Error in save_compensation: {e}")
        await update.message.reply_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def confirm_totals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm trade totals and create offer"""
    try:
        query = update.callback_query
        await query.answer()

        selected_items = context.user_data.get('selected_items', [])
        pharmacy = context.user_data.get('selected_pharmacy', {})
        
        if not selected_items or not pharmacy:
            await query.answer("خطا در پردازش. لطفا دوباره تلاش کنید.", show_alert=True)
            return ConversationHandler.END
            
        # Calculate totals
        pharmacy_total = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in selected_items if item.get('type') == 'pharmacy_drug'
        )
        
        buyer_total = sum(
            parse_price(item['price']) * item.get('selected_quantity', 1)
            for item in selected_items if item.get('type') in ('buyer_drug', 'compensation')
        )
        
        difference = pharmacy_total - buyer_total
        
        message = (
            "📋 خلاصه پیشنهاد تبادل:\n\n"
            f"🔹 داروخانه: {pharmacy.get('name')}\n\n"
            "💊 داروهای دریافتی از داروخانه:\n"
        )
        
        for item in selected_items:
            if item.get('type') == 'pharmacy_drug':
                message += (
                    f"• {item['name']} - قیمت: {item['price']} "
                    f"(تعداد: {item.get('selected_quantity', 1)})\n"
                )
        
        message += "\n📝 داروهای ارسالی شما:\n"
        for item in selected_items:
            if item.get('type') in ('buyer_drug', 'compensation'):
                message += (
                    f"• {item['name']} - قیمت: {item['price']} "
                    f"(تعداد: {item.get('selected_quantity', 1)})\n"
                )
        
        message += (
            f"\n💰 جمع دریافتی: {pharmacy_total:,}\n"
            f"💰 جمع ارسالی: {buyer_total:,}\n"
            f"🔹 تفاوت: {abs(difference):,} "
            f"({'به نفع شما' if difference < 0 else 'به نفع داروخانه'})\n\n"
            "آیا مایل به ثبت این پیشنهاد هستید؟"
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ تایید و ارسال", callback_data="confirm_offer")],
            [InlineKeyboardButton("✏️ ویرایش", callback_data="edit_selection")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_totals")]
        ]
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard))
        return States.CONFIRM_OFFER
    except Exception as e:
        logger.error(f"Error in confirm_totals: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def create_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create trade offer in database"""
    try:
        query = update.callback_query
        await query.answer()

        selected_items = context.user_data.get('selected_items', [])
        pharmacy = context.user_data.get('selected_pharmacy', {})
        
        if not selected_items or not pharmacy:
            await query.answer("خطا در پردازش. لطفا دوباره تلاش کنید.", show_alert=True)
            return ConversationHandler.END
            
        conn = None
        try:
            # Calculate total price
            pharmacy_total = sum(
                parse_price(item['price']) * item.get('selected_quantity', 1)
                for item in selected_items if item.get('type') == 'pharmacy_drug'
            )
            
            # Create offer
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO offers (
                pharmacy_id, buyer_id, total_price
            ) VALUES (%s, %s, %s)
            RETURNING id
            ''', (
                pharmacy['id'],
                update.effective_user.id,
                pharmacy_total
            ))
            offer_id = cursor.fetchone()[0]
            
            # Add offer items
            for item in selected_items:
                if item.get('type') == 'pharmacy_drug':
                    cursor.execute('''
                    INSERT INTO offer_items (
                        offer_id, drug_name, price, quantity, item_type
                    ) VALUES (%s, %s, %s, %s, 'drug')
                    ''', (
                        offer_id,
                        item['name'],
                        item['price'],
                        item.get('selected_quantity', 1)
                    ))
                elif item.get('type') in ('buyer_drug', 'compensation'):
                    cursor.execute('''
                    INSERT INTO compensation_items (
                        offer_id, drug_id, quantity
                    ) VALUES (%s, %s, %s)
                    ''', (
                        offer_id,
                        item['id'],
                        item.get('selected_quantity', 1)
                    ))
            
            conn.commit()
            
            # Notify pharmacy
            try:
                keyboard = [
                    [InlineKeyboardButton("✅ پذیرش پیشنهاد", callback_data=f"offer_accept_{offer_id}")],
                    [InlineKeyboardButton("❌ رد پیشنهاد", callback_data=f"offer_reject_{offer_id}")]
                ]
                
                offer_message = (
                    "📬 یک پیشنهاد تبادل جدید دریافت کردید:\n\n"
                    f"از: {update.effective_user.full_name}\n\n"
                    "💊 داروهای پیشنهادی:\n"
                )
                
                for item in selected_items:
                    if item.get('type') == 'pharmacy_drug':
                        offer_message += (
                            f"• {item['name']} - قیمت: {item['price']} "
                            f"(تعداد: {item.get('selected_quantity', 1)})\n"
                        )
                
                offer_message += "\n📝 داروهای دریافتی:\n"
                for item in selected_items:
                    if item.get('type') in ('buyer_drug', 'compensation'):
                        offer_message += (
                            f"• {item['name']} - قیمت: {item['price']} "
                            f"(تعداد: {item.get('selected_quantity', 1)})\n"
                        )
                
                offer_message += (
                    f"\n💰 جمع مبلغ: {pharmacy_total:,}\n\n"
                    "لطفا این پیشنهاد را بررسی کنید:"
                )
                
                await context.bot.send_message(
                    chat_id=pharmacy['id'],
                    text=offer_message,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
            except Exception as e:
                logger.error(f"Failed to notify pharmacy: {e}")
            
            await query.edit_message_text(
                "✅ پیشنهاد تبادل شما با موفقیت ثبت شد!\n\n"
                "پس از بررسی توسط داروخانه، نتیجه به شما اطلاع داده خواهد شد."
            )
                
        except Exception as e:
            logger.error(f"Error creating offer: {e}")
            await query.answer("خطا در ثبت پیشنهاد. لطفا دوباره تلاش کنید.", show_alert=True)
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
                
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in create_offer: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def handle_offer_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pharmacy's response to offer"""
    try:
        query = update.callback_query
        await query.answer()

        if not query.data.startswith(("offer_accept_", "offer_reject_")):
            return
            
        action, offer_id = query.data.split("_")[1], int(query.data.split("_")[2])
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                # Get offer details
                cursor.execute('''
                SELECT o.id, o.pharmacy_id, o.buyer_id, o.total_price,
                       p.name as pharmacy_name,
                       u.first_name || ' ' || u.last_name as buyer_name
                FROM offers o
                JOIN pharmacies p ON o.pharmacy_id = p.user_id
                JOIN users u ON o.buyer_id = u.id
                WHERE o.id = %s
                ''', (offer_id,))
                offer = cursor.fetchone()
                
                if not offer:
                    await query.answer("پیشنهاد یافت نشد", show_alert=True)
                    return
                
                # Update offer status
                if action == "accept":
                    cursor.execute('''
                    UPDATE offers 
                    SET status = 'accepted'
                    WHERE id = %s
                    ''', (offer_id,))
                    
                    # Get offer items to update quantities
                    cursor.execute('''
                    SELECT drug_name, quantity 
                    FROM offer_items 
                    WHERE offer_id = %s
                    ''', (offer_id,))
                    offer_items = cursor.fetchall()
                    
                    for item in offer_items:
                        cursor.execute('''
                        UPDATE drug_items 
                        SET quantity = quantity - %s
                        WHERE user_id = %s AND name = %s AND quantity >= %s
                        ''', (
                            item['quantity'],
                            offer['pharmacy_id'],
                            item['drug_name'],
                            item['quantity']
                        ))
                    
                    # Get compensation items
                    cursor.execute('''
                    SELECT di.id, di.name, c.quantity
                    FROM compensation_items c
                    JOIN drug_items di ON c.drug_id = di.id
                    WHERE c.offer_id = %s
                    ''', (offer_id,))
                    compensation_items = cursor.fetchall()
                    
                    for item in compensation_items:
                        cursor.execute('''
                        UPDATE drug_items 
                        SET quantity = quantity - %s
                        WHERE id = %s AND quantity >= %s
                        ''', (
                            item['quantity'],
                            item['id'],
                            item['quantity']
                        ))
                    
                    # Notify buyer
                    try:
                        await context.bot.send_message(
                            chat_id=offer['buyer_id'],
                            text=(
                                "✅ پیشنهاد تبادل شما پذیرفته شد!\n\n"
                                f"داروخانه: {offer['pharmacy_name']}\n"
                                "می‌توانید برای هماهنگی بیشتر با داروخانه تماس بگیرید."
                            )
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify buyer: {e}")
                    
                    await query.edit_message_text(
                        "✅ پیشنهاد تبادل پذیرفته شد!\n\n"
                        "اطلاعات به خریدار ارسال شد."
                    )
                    
                else:  # reject
                    cursor.execute('''
                    UPDATE offers 
                    SET status = 'rejected'
                    WHERE id = %s
                    ''', (offer_id,))
                    
                    # Notify buyer
                    try:
                        await context.bot.send_message(
                            chat_id=offer['buyer_id'],
                            text=(
                                "❌ پیشنهاد تبادل شما رد شد.\n\n"
                                f"داروخانه: {offer['pharmacy_name']}\n"
                                "می‌توانید پیشنهاد جدیدی ارسال کنید."
                            )
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify buyer: {e}")
                    
                    await query.edit_message_text(
                        "❌ پیشنهاد تبادل رد شد.\n\n"
                        "اطلاعات به خریدار ارسال شد."
                    )
                
                conn.commit()
                
        except Exception as e:
            logger.error(f"Error handling offer response: {e}")
            await query.answer("خطا در پردازش پیشنهاد", show_alert=True)
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"Error in handle_offer_response: {e}")
        await update.callback_query.edit_message_text("خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

async def handle_match_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle match notification response"""
    try:
        query = update.callback_query
        await query.answer()

        if not query.data.startswith("view_match_"):
            return
            
        _, drug_id, need_id = query.data.split("_")
        drug_id, need_id = int(drug_id), int(need_id)
        
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
                SELECT id, name, description, quantity 
                FROM user_needs 
                WHERE id = %s
                ''', (need_id,))
                need = cursor.fetchone()
                
                if not drug or not need:
                    await query.answer("اطلاعات یافت نشد", show_alert=True)
                    return
                
                # Store in context for trade process
                context.user_data['selected_pharmacy'] = {
                    'id': drug['pharmacy_id'],
                    'name': drug['pharmacy_name']
                }
                context.user_data['pharmacy_drugs'] = [dict(drug)]
                context.user_data['selected_items'] = [{
                    'id': drug['id'],
                    'name': drug['name'],
                    'price': drug['price'],
                    'quantity': drug['quantity'],
                    'type': 'pharmacy_drug',
                    'selected_quantity': min(drug['quantity'], need['quantity'])
                }]
                
                # Get buyer's drugs for potential exchange
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
                ''', (drug['pharmacy_id'],))
                pharmacy_categories = cursor.fetchall()
                context.user_data['pharmacy_categories'] = [dict(row) for row in pharmacy_categories]
                
                # Show trade interface
                return await show_two_column_selection(update, context)
                
        except Exception as e:
            logger.error(f"Error handling match: {e}")
            await query.answer("خطا در پردازش", show_alert=True)
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
    """Handle errors in the bot"""
    try:
        logger.error(f"Update {update} caused error: {context.error}")
        
        if update and update.effective_user:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_user.id,
                    text="متاسفانه خطایی رخ داده است. لطفا دوباره تلاش کنید."
                )
            except Exception as e:
                logger.error(f"Failed to send error message: {e}")
    except Exception as e:
        logger.error(f"Error in error_handler: {e}")

async def post_init(application: Application):
    """Post initialization tasks"""
    try:
        await initialize_db()
        if not load_drug_data():
            logger.warning("Failed to load drug data")
    except Exception as e:
        logger.error(f"Error in post_init: {e}")
def main():
    """Main function to start the bot"""
    try:
        # Create application
        application = ApplicationBuilder() \
            .token("7551102128:AAEYxAtdyGh21CwmjvnvqKNq8FyR6PijHsY") \
            .post_init(post_init) \
            .build()

        # conversation handlers
        registration_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(register_pharmacy_name, pattern="^register$")],
            states={
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
                    MessageHandler(filters.CONTACT, register_address),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, register_address)
                ],
                States.REGISTER_ADDRESS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, register_location)
                ],
                States.REGISTER_LOCATION: [
                    MessageHandler(filters.LOCATION, verify_code)
                ],
                States.VERIFICATION_CODE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complete_registration)
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            allow_reentry=True
        )

        admin_verify_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_verify_start, pattern="^admin_verify$")],
            states={
                States.ADMIN_VERIFICATION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_verify_code)
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            allow_reentry=True
        )

        simple_verify_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(simple_verify_start, pattern="^simple_verify$")],
            states={
                States.SIMPLE_VERIFICATION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, simple_verify_code)
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            allow_reentry=True
        )

        add_drug_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex(r"^اضافه کردن دارو$"), add_drug_item)],
            states={
                States.SEARCH_DRUG_FOR_ADDING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, search_drug_for_adding)
                ],
                States.SELECT_DRUG_FOR_ADDING: [
                    CallbackQueryHandler(select_drug_for_adding)
                ],
                States.ADD_DRUG_DATE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, add_drug_date),
                    CallbackQueryHandler(search_drug_for_adding, pattern=r"^back_to_search$")
                ],
                States.ADD_DRUG_QUANTITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_drug_item),
                    CallbackQueryHandler(select_drug_for_adding, pattern=r"^back_to_drug_selection$")
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            allow_reentry=True
        )

        search_drug_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex(r"^جستجوی دارو$"), search_drug)],
            states={
                States.SEARCH_DRUG: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search)
                ],
                States.SELECT_PHARMACY: [
                    CallbackQueryHandler(select_pharmacy)
                ],
                States.SELECT_ITEMS: [
                    CallbackQueryHandler(select_items)
                ],
                States.CONFIRM_TOTALS: [
                    CallbackQueryHandler(confirm_totals)
                ],
                States.COMPENSATION_SELECTION: [
                    CallbackQueryHandler(handle_compensation_selection)
                ],
                States.COMPENSATION_QUANTITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_compensation),
                    CallbackQueryHandler(confirm_totals, pattern=r"^back_to_totals$")
                ],
                States.CONFIRM_OFFER: [
                    CallbackQueryHandler(create_offer)
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            allow_reentry=True
        )

        add_need_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex(r"^ثبت نیاز جدید$"), add_need)],
            states={
                States.ADD_NEED_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_need_name)
                ],
                States.ADD_NEED_DESC: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_need_desc)
                ],
                States.ADD_NEED_QUANTITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_need)
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            allow_reentry=True
        )
        edit_drug_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(edit_drugs, pattern=r"^edit_drugs$")],
            states={
                States.EDIT_DRUG: [
                    CallbackQueryHandler(edit_drug_item, pattern=r"^edit_drug_\d+$"),
                    CallbackQueryHandler(handle_drug_edit_action, pattern=r"^(delete_drug_\d+|confirm_delete_\d+|cancel_delete_\d+)"),
                    CallbackQueryHandler(
                        handle_drug_edit_action,
                        pattern=r"^(edit_date|edit_quantity|delete_drug|back_to_list|confirm_delete|cancel_delete)$"
                    ),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_drug_edit)
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            allow_reentry=True
        )

        edit_need_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(edit_needs, pattern=r"^edit_needs$")],
            states={
                States.EDIT_NEED: [
                    CallbackQueryHandler(edit_need_item, pattern=r"^edit_need_\d+$"),
                    CallbackQueryHandler(handle_need_edit_action, pattern=r"^(delete_need_\d+|confirm_need_delete_\d+|cancel_need_delete_\d+)"),
                    CallbackQueryHandler(
                        handle_need_edit_action,
                        pattern=r"^(edit_need_name|edit_need_desc|edit_need_quantity|delete_need|back_to_needs_list|confirm_need_delete|cancel_need_delete)$"
                    ),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, save_need_edit)
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            allow_reentry=True
        )

        admin_excel_handler = ConversationHandler(
            entry_points=[CommandHandler("upload_excel", upload_excel_start)],
            states={
                States.ADMIN_UPLOAD_EXCEL: [
                    MessageHandler(filters.Document.ALL | filters.TEXT & ~filters.COMMAND, handle_excel_upload)
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            allow_reentry=True
        )

        # Add all handlers to application
        application.add_handler(CommandHandler("start", start))
        application.add_handler(registration_handler)
        application.add_handler(admin_verify_handler)
        application.add_handler(simple_verify_handler)
        application.add_handler(add_drug_handler)
        application.add_handler(search_drug_handler)
        application.add_handler(add_need_handler)
        application.add_handler(edit_drug_handler)
        application.add_handler(edit_need_handler)
        application.add_handler(admin_excel_handler)
        application.add_handler(CommandHandler("generate_code", generate_simple_code))
        application.add_handler(CallbackQueryHandler(
        add_drug_from_search, 
        pattern=r"^add_drug_"
        ))

        # Additional callback handlers
        application.add_handler(CallbackQueryHandler(
            handle_drug_edit_action,
            pattern=r"^(edit_name|edit_price|edit_date|edit_quantity|delete_drug)$"
        ))
        application.add_handler(MessageHandler(
            filters.Regex(r"^لیست داروهای من$"),
            list_my_drugs
        ))
        application.add_handler(MessageHandler(
            filters.Regex(r"^لیست نیازهای من$"),
            list_my_needs
        ))
        application.add_handler(MessageHandler(
        filters.Regex(r"^تنظیم شاخه‌های دارویی$"),
        setup_medical_categories
        ))
        application.add_handler(CallbackQueryHandler(callback_handler))
        application.add_error_handler(error_handler)

        # Start the bot
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Error in main: {e}")

if __name__ == "__main__":
    main()
        
        
    
