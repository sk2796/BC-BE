import os
import re
import hmac
import hashlib
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
import razorpay
import bcrypt
from dotenv import load_dotenv

def hash_password(plain_password: str) -> str:
    """Hash a password using bcrypt with a salt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain_password.encode('utf-8'), salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against its bcrypt hash."""
    if not hashed_password:
        return False
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

# Load credentials from .env configurations file
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "chhotelalpeda@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

def send_reset_email(to_email: str, recipient_name: str, reset_link: str) -> bool:
    """Send an HTML password reset email from chhotelalpeda@gmail.com via SMTP."""
    subject = "BloomCakes - Password Reset Request"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: 'Helvetica Neue', Arial, sans-serif; background-color: #fff8f6; color: #2d150d; margin: 0; padding: 20px; }}
        .container {{ max-width: 540px; margin: 0 auto; background: #ffffff; border-radius: 16px; border: 1px solid #ddc0b8; overflow: hidden; box-shadow: 0 4px 20px rgba(159, 65, 34, 0.08); }}
        .header {{ background-color: #9f4122; color: #ffffff; padding: 24px; text-align: center; }}
        .header h1 {{ margin: 0; font-size: 24px; font-weight: bold; letter-spacing: -0.5px; }}
        .content {{ padding: 32px 28px; line-height: 1.6; font-size: 15px; color: #56423c; }}
        .btn {{ display: inline-block; background-color: #9f4122; color: #ffffff !important; padding: 14px 28px; border-radius: 30px; text-decoration: none; font-weight: bold; font-size: 14px; margin: 24px 0; text-transform: uppercase; letter-spacing: 0.5px; box-shadow: 0 4px 12px rgba(159, 65, 34, 0.25); }}
        .footer {{ border-top: 1px solid #f2e3df; padding: 20px 28px; font-size: 12px; color: #89726b; text-align: center; }}
        .link-text {{ word-break: break-all; font-size: 12px; color: #9f4122; }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <h1>BloomCakes</h1>
        </div>
        <div class="content">
          <p>Hello <strong>{recipient_name}</strong>,</p>
          <p>We received a request to reset your password for your BloomCakes account.</p>
          <p style="text-align: center;">
            <a href="{reset_link}" class="btn">Reset My Password</a>
          </p>
          <p>This password reset link is valid for <strong>1 hour</strong>. If you did not request a password reset, you can safely ignore this email.</p>
          <p>Or copy and paste this link into your browser:<br>
          <a href="{reset_link}" class="link-text">{reset_link}</a></p>
        </div>
        <div class="footer">
          <p>&copy; {datetime.now().year} BloomCakes. All rights reserved.<br>Sent with love from chhotelalpeda@gmail.com</p>
        </div>
      </div>
    </body>
    </html>
    """

    if not SMTP_PASSWORD:
        print(f"[Email Sim] SMTP_PASSWORD not set. Password reset link for {to_email}: {reset_link}")
        return True

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"BloomCakes <{SMTP_USER}>"
        msg["To"] = to_email

        plain_text = f"Hello {recipient_name},\n\nClick the link below to reset your BloomCakes password:\n{reset_link}\n\nThis link expires in 1 hour."
        msg.attach(MIMEText(plain_text, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, to_email, msg.as_string())
        server.quit()
        print(f"Password reset email sent to {to_email} via {SMTP_USER}")
        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
        return False

try:
    from backend.database import engine, Base, get_db
    from backend.models import ProductModel, PincodeModel, OrderModel, CustomerModel, AdminUserModel, DeliveryModel
    from backend.services.shipping import (
        get_shipping_provider, get_available_providers, get_pickup_address,
        Address, DELIVERY_TO_ORDER_STATUS
    )
except ImportError:
    from database import engine, Base, get_db
    from models import ProductModel, PincodeModel, OrderModel, CustomerModel, AdminUserModel, DeliveryModel
    from services.shipping import (
        get_shipping_provider, get_available_providers, get_pickup_address,
        Address, DELIVERY_TO_ORDER_STATUS
    )

import json
import asyncio

# Load credentials from .env configurations file
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

# Initialize Razorpay Client wrapper
razorpay_client = None
if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# Ensure database tables exist
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="BloomCakes Backend API",
    description="Backend APIs with MySQL Database and SQLAlchemy ORM integration",
    version="2.0.0"
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models for validation and responses
class CakeItem(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    price: int
    category: str
    imageUrl: str
    isBestseller: bool
    rating: float

    class Config:
        from_attributes = True

class ProductCreateRequest(BaseModel):
    name: str
    category: str
    price: int
    description: Optional[str] = None
    imageUrl: str
    isBestseller: Optional[bool] = False
    rating: Optional[float] = 4.8

class ProductUpdateRequest(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    price: Optional[int] = None
    description: Optional[str] = None
    imageUrl: Optional[str] = None
    isBestseller: Optional[bool] = None
    rating: Optional[float] = None

class PincodeCreateRequest(BaseModel):
    pincode: str
    city: str
    state: str

class PincodeItem(BaseModel):
    pincode: str
    city: str
    state: Optional[str] = None

    class Config:
        from_attributes = True

class OrderSummaryItem(BaseModel):
    cakeId: str
    name: str
    weight: str
    price: int
    quantity: int

class OrderSubmission(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    customer_id: Optional[str] = None
    addressLine1: str
    landmark: Optional[str] = None
    city: str
    pincode: str
    date: str
    timeSlot: str
    occasion: str
    customOccasion: Optional[str] = None
    items: List[OrderSummaryItem]
    activePromo: Optional[str] = None
    discountAmount: int = 0
    totalAmount: int
    status: Optional[str] = "order_confirmed"

class OrderStatusUpdate(BaseModel):
    status: str  # order_confirmed, dispatched, shipped, delivered, cancelled


class DeliveryDispatchRequest(BaseModel):
    provider: str = "manual"  # borzo, porter, manual
    package_description: Optional[str] = None

class DeliveryQuoteRequest(BaseModel):
    provider: str = "manual"


class CreateOrderRequest(BaseModel):
    amount: int  # in paise
    currency: str = "INR"
    receipt: Optional[str] = None

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str

class CustomerDetails(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    password: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None

class CustomerRegisterRequest(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    password: str

class CustomerLoginRequest(BaseModel):
    identifier: str  # Email or 10-digit phone number
    password: str

class ForgotPasswordRequest(BaseModel):
    identifier: str  # Email or 10-digit phone number

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class AdminLoginRequest(BaseModel):
    email: str
    password: str

class AdminUserCreateRequest(BaseModel):
    name: str
    email: str
    password: str
    role: str = "manager"  # super_admin, manager, delivery_staff, catalog_editor
    is_active: bool = True

class AdminUserUpdateRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


def clean_phone_to_10_digits(phone: str) -> str:
    digits = "".join(filter(str.isdigit, str(phone)))
    if len(digits) == 12 and digits.startswith("91"):
        return digits[2:]
    if len(digits) >= 10:
        return digits[-10:]
    return digits


# Endpoints

@app.get("/")
def read_root():
    return {"message": "Welcome to BloomCakes Backend API. Visit /docs for Swagger specifications documentation."}

@app.get("/health")
@app.get("/healthz")
def health_check():
    return {"status": "healthy"}

@app.get("/products", response_model=List[CakeItem])
def get_products(db: Session = Depends(get_db)):
    """Retrieve all cake catalog items from MySQL Database."""
    products = db.query(ProductModel).all()
    if not products:
        raise HTTPException(status_code=404, detail="No products found in database.")
    return products

@app.get("/products/{slug}", response_model=CakeItem)
def get_product_by_slug(slug: str, db: Session = Depends(get_db)):
    """Retrieve a single cake product matched by its unique slug from MySQL Database."""
    product = db.query(ProductModel).filter(ProductModel.slug == slug).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")
    return product

@app.get("/pincodes")
def check_pincode(code: str, db: Session = Depends(get_db)):
    """Check if a specific pincode is serviceable in MySQL Database."""
    item = db.query(PincodeModel).filter(PincodeModel.pincode == code.strip()).first()
    if item:
        return {"serviceable": True, "city": item.city, "state": item.state}
CATEGORY_CODE_MAP = {
    "cakes": "CAKE",
    "muffins": "MUF",
    "cupcakes": "CUP",
    "pastries": "PAS",
    "brownies": "BRW",
    "fruit-pies": "PIE",
    "cookies": "COK",
}

def generate_product_slug(name: str, db: Session, current_id: Optional[str] = None) -> str:
    """Generate clean URL slug from name, handling duplicates gracefully."""
    base_slug = re.sub(r"[^\w\s-]", "", name.lower()).strip()
    base_slug = re.sub(r"[-\s]+", "-", base_slug)
    if not base_slug:
        base_slug = "product"
    
    slug = base_slug
    counter = 1
    while True:
        query = db.query(ProductModel).filter(ProductModel.slug == slug)
        if current_id:
            query = query.filter(ProductModel.id != current_id)
        if not query.first():
            return slug
        counter += 1
        slug = f"{base_slug}-{counter}"

def generate_product_id(name: str, category: str, db: Session) -> str:
    """Generate meaningful product ID e.g. BC-CAKE-BELGIAN-CHOC."""
    cat_key = category.strip().lower()
    prefix = CATEGORY_CODE_MAP.get(cat_key, "ITM")
    
    # Clean product title words
    clean_words = re.sub(r"[^\w\s]", "", name.upper()).split()
    # Take first 3-4 key initials/words up to 20 chars
    code_part = "-".join(clean_words[:4])[:20].rstrip("-")
    if not code_part:
        code_part = "PROD"
        
    base_id = f"BC-{prefix}-{code_part}"
    candidate_id = base_id
    counter = 1
    while db.query(ProductModel).filter(ProductModel.id == candidate_id).first():
        counter += 1
        candidate_id = f"{base_id}-{counter}"
    return candidate_id

@app.get("/admin/analytics")
def get_admin_analytics(db: Session = Depends(get_db)):
    """Summary analytics for SaaS Admin Portal."""
    try:
        total_products = db.query(ProductModel).count()
        total_customers = db.query(CustomerModel).count()
        orders = db.query(OrderModel).all()
        total_orders = len(orders)
        
        total_revenue = sum(o.totalAmount for o in orders if (o.status or "") != "cancelled")
        
        status_counts = {
            "order_confirmed": 0,
            "shipped": 0,
            "delivered": 0,
            "cancelled": 0
        }
        for o in orders:
            st = o.status or "order_confirmed"
            status_counts[st] = status_counts.get(st, 0) + 1
            
        recent_orders = [
            {
                "order_id": o.order_id,
                "name": o.name,
                "phone": o.phone,
                "totalAmount": o.totalAmount,
                "status": o.status or "order_confirmed",
                "created_at": o.created_at
            }
            for o in sorted(orders, key=lambda x: x.id, reverse=True)[:5]
        ]
        
        return {
            "total_revenue": total_revenue,
            "total_orders": total_orders,
            "total_customers": total_customers,
            "total_products": total_products,
            "status_counts": status_counts,
            "recent_orders": recent_orders
        }
    except Exception as e:
        print(f"Error compiling analytics: {e}")
        return {
            "total_revenue": 0,
            "total_orders": 0,
            "total_customers": 0,
            "total_products": 0,
            "status_counts": {},
            "recent_orders": []
        }

@app.post("/admin/auth/login")
def admin_login(payload: AdminLoginRequest, db: Session = Depends(get_db)):
    """Authenticate admin or staff user and return their role and permissions."""
    email_clean = payload.email.strip().lower()
    user = db.query(AdminUserModel).filter(AdminUserModel.email == email_clean).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid admin credentials.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Your staff account has been deactivated. Contact Super Admin.")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid admin credentials.")
        
    return {
        "success": True,
        "admin_user": {
            "admin_id": user.admin_id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active
        },
        "token": f"adm_sec_{user.admin_id}_{secrets.token_hex(16)}"
    }

@app.get("/admin/users")
def get_all_admin_users(db: Session = Depends(get_db)):
    """Retrieve all staff accounts with their roles and status."""
    users = db.query(AdminUserModel).order_by(AdminUserModel.id.asc()).all()
    return [
        {
            "id": u.id,
            "admin_id": u.admin_id,
            "name": u.name,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at
        }
        for u in users
    ]

@app.post("/admin/users")
def create_admin_user(payload: AdminUserCreateRequest, db: Session = Depends(get_db)):
    """Create a new staff member account and assign specific role."""
    email_clean = payload.email.strip().lower()
    existing = db.query(AdminUserModel).filter(AdminUserModel.email == email_clean).first()
    if existing:
        raise HTTPException(status_code=400, detail="Staff member with this email already exists.")
        
    # Generate unique admin_id
    role_prefix = {
        "super_admin": "SA",
        "manager": "MGR",
        "delivery_staff": "DEL",
        "catalog_editor": "CAT"
    }.get(payload.role, "STF")
    
    count = db.query(AdminUserModel).count() + 1
    admin_id = f"BC-{role_prefix}-{count:03d}"
    
    new_user = AdminUserModel(
        admin_id=admin_id,
        name=payload.name.strip(),
        email=email_clean,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=payload.is_active
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {
        "success": True,
        "user": {
            "id": new_user.id,
            "admin_id": new_user.admin_id,
            "name": new_user.name,
            "email": new_user.email,
            "role": new_user.role,
            "is_active": new_user.is_active,
            "created_at": new_user.created_at
        }
    }

@app.patch("/admin/users/{admin_id}")
def update_admin_user(admin_id: str, payload: AdminUserUpdateRequest, db: Session = Depends(get_db)):
    """Update role, status, or reset password for an admin staff user."""
    user = db.query(AdminUserModel).filter(AdminUserModel.admin_id == admin_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Staff user not found.")
        
    if payload.name is not None:
        user.name = payload.name.strip()
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None and payload.password.strip():
        user.password_hash = hash_password(payload.password.strip())
        
    user.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.commit()
    db.refresh(user)
    return {
        "success": True,
        "user": {
            "admin_id": user.admin_id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active
        }
    }

@app.delete("/admin/users/{admin_id}")
def delete_admin_user(admin_id: str, db: Session = Depends(get_db)):
    """Delete a staff user."""
    user = db.query(AdminUserModel).filter(AdminUserModel.admin_id == admin_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Staff user not found.")
    if user.role == "super_admin" and db.query(AdminUserModel).filter(AdminUserModel.role == "super_admin").count() <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the only Super Admin account.")
    db.delete(user)
    db.commit()
    return {"success": True, "message": f"Staff user {admin_id} deleted."}

@app.post("/admin/products", response_model=CakeItem)
def create_product(payload: ProductCreateRequest, db: Session = Depends(get_db)):
    """Create a new product with auto-generated meaningful ID and URL slug."""
    new_id = generate_product_id(payload.name, payload.category, db)
    new_slug = generate_product_slug(payload.name, db)
    
    new_prod = ProductModel(
        id=new_id,
        name=payload.name.strip(),
        slug=new_slug,
        description=payload.description.strip() if payload.description else "",
        price=payload.price,
        category=payload.category.strip().lower(),
        imageUrl=payload.imageUrl.strip(),
        isBestseller=bool(payload.isBestseller),
        rating=float(payload.rating or 4.8)
    )
    
    db.add(new_prod)
    db.commit()
    db.refresh(new_prod)
    return new_prod

@app.put("/admin/products/{product_id}", response_model=CakeItem)
def update_product(product_id: str, payload: ProductUpdateRequest, db: Session = Depends(get_db)):
    """Update an existing product's details and dynamically adjust slug if name changed."""
    product = db.query(ProductModel).filter(ProductModel.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
        
    if payload.name is not None and payload.name.strip() != product.name:
        product.name = payload.name.strip()
        product.slug = generate_product_slug(payload.name, db, current_id=product_id)
        
    if payload.category is not None:
        product.category = payload.category.strip().lower()
    if payload.price is not None:
        product.price = payload.price
    if payload.description is not None:
        product.description = payload.description.strip()
    if payload.imageUrl is not None:
        product.imageUrl = payload.imageUrl.strip()
    if payload.isBestseller is not None:
        product.isBestseller = payload.isBestseller
    if payload.rating is not None:
        product.rating = payload.rating
        
    db.commit()
    db.refresh(product)
    return product

@app.delete("/admin/products/{product_id}")
def delete_product(product_id: str, db: Session = Depends(get_db)):
    """Remove a product from the database catalog."""
    product = db.query(ProductModel).filter(ProductModel.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(product)
    db.commit()
    return {"success": True, "message": f"Product {product_id} deleted successfully."}

@app.get("/admin/pincodes")
def get_all_pincodes(db: Session = Depends(get_db)):
    """Retrieve all serviceable pincodes."""
    return db.query(PincodeModel).order_by(PincodeModel.pincode.asc()).all()

@app.post("/admin/pincodes")
def add_pincode(payload: PincodeCreateRequest, db: Session = Depends(get_db)):
    """Add a new serviceable pincode."""
    existing = db.query(PincodeModel).filter(PincodeModel.pincode == payload.pincode.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Pincode already exists in serviceable list.")
    new_pin = PincodeModel(
        pincode=payload.pincode.strip(),
        city=payload.city.strip(),
        state=payload.state.strip()
    )
    db.add(new_pin)
    db.commit()
    return {"success": True, "pincode": new_pin.pincode}

@app.delete("/admin/pincodes/{code}")
def delete_pincode(code: str, db: Session = Depends(get_db)):
    """Remove a serviceable pincode."""
    item = db.query(PincodeModel).filter(PincodeModel.pincode == code.strip()).first()
    if not item:
        raise HTTPException(status_code=404, detail="Pincode not found")
    db.delete(item)
    db.commit()
    return {"success": True, "message": f"Pincode {code} removed."}

@app.get("/admin/orders")
def get_all_orders(db: Session = Depends(get_db)):
    """Retrieve all saved order records from MySQL Database."""
    try:
        orders = db.query(OrderModel).order_by(OrderModel.id.desc()).all()
        result = []
        for o in orders:
            result.append({
                "order_id": o.order_id,
                "customer_id": o.customer_id,
                "name": o.name,
                "phone": o.phone,
                "email": o.email,
                "addressLine1": o.addressLine1,
                "landmark": o.landmark,
                "city": o.city,
                "pincode": o.pincode,
                "date": o.date,
                "timeSlot": o.timeSlot,
                "occasion": o.occasion,
                "customOccasion": o.customOccasion,
                "items_summary": o.items_summary,
                "activePromo": o.activePromo,
                "discountAmount": o.discountAmount,
                "totalAmount": o.totalAmount,
                "status": o.status or "order_confirmed",
                "created_at": o.created_at
            })
        return result
    except Exception as e:
        print(f"Error reading orders from DB: {e}")
        return []

@app.get("/admin/customers")
def get_all_customers(db: Session = Depends(get_db)):
    """Retrieve all saved customer records from MySQL Database."""
    try:
        customers = db.query(CustomerModel).order_by(CustomerModel.id.desc()).all()
        result = []
        for c in customers:
            result.append({
                "customer_id": c.customer_id,
                "name": c.name,
                "phone": c.phone,
                "email": c.email,
                "city": c.city,
                "state": c.state,
                "pincode": c.pincode,
                "updated_at": c.updated_at
            })
        return result
    except Exception as e:
        print(f"Error reading customers from DB: {e}")
        return []

@app.post("/orders")
def submit_order(order: OrderSubmission, db: Session = Depends(get_db)):
    """Save order record to MySQL Database mapped to customer_id."""
    clean_phone = clean_phone_to_10_digits(order.phone)
    phone_suffix = clean_phone[-4:] if len(clean_phone) >= 4 else "0000"
    
    order_id = f"BC-ORD-{phone_suffix}-{order.date.replace('-', '')}"
    items_summary = ", ".join([f"{item.name} ({item.weight}) x{item.quantity}" for item in order.items])
    
    # Associate with existing customer or supplied customer_id
    matched_cust_id = order.customer_id
    if not matched_cust_id:
        existing_cust = db.query(CustomerModel).filter(CustomerModel.phone == clean_phone).first()
        if existing_cust:
            matched_cust_id = existing_cust.customer_id
        else:
            name_clean = "".join(filter(str.isalpha, order.name)).upper()
            name_prefix = name_clean[:3] if len(name_clean) >= 3 else "CST"
            matched_cust_id = f"BC-CUST-{name_prefix}-{phone_suffix}"
            # Also auto-create customer record if they don't exist yet
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                new_cust = CustomerModel(
                    customer_id=matched_cust_id,
                    name=order.name,
                    phone=clean_phone,
                    email=order.email or None,
                    city=order.city,
                    pincode=order.pincode,
                    created_at=now_str,
                    updated_at=now_str
                )
                db.add(new_cust)
                db.commit()
            except Exception as ex:
                db.rollback()
                print(f"Customer auto-creation note: {ex}")

    try:
        new_order = OrderModel(
            order_id=order_id,
            customer_id=matched_cust_id,
            name=order.name,
            phone=clean_phone,
            email=order.email or None,
            addressLine1=order.addressLine1,
            landmark=order.landmark or None,
            city=order.city,
            pincode=order.pincode,
            date=order.date,
            timeSlot=order.timeSlot,
            occasion=order.occasion,
            customOccasion=order.customOccasion or None,
            items_summary=items_summary,
            activePromo=order.activePromo or None,
            discountAmount=order.discountAmount,
            totalAmount=order.totalAmount,
            status=order.status or "order_confirmed",
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        db.add(new_order)
        db.commit()
        db.refresh(new_order)
        print(f"Stored order {order_id} mapped to customer {matched_cust_id} with status {new_order.status}.")
    except Exception as e:
        db.rollback()
        print(f"Error saving order to DB: {e}")
        raise HTTPException(status_code=500, detail="Failed to save order to database.")

    return {
        "status": "success",
        "order_id": order_id,
        "customer_id": matched_cust_id,
        "order_status": new_order.status,
        "message": "Order processed and stored successfully"
    }

@app.post("/customers")
def save_customer(customer: CustomerDetails, db: Session = Depends(get_db)):
    """Save or update customer profile in MySQL Database."""
    clean_phone = clean_phone_to_10_digits(customer.phone)
    phone_suffix = clean_phone[-4:] if len(clean_phone) >= 4 else "0000"
    name_clean = "".join(filter(str.isalpha, customer.name)).upper()
    name_prefix = name_clean[:3] if len(name_clean) >= 3 else "CST"
    generated_cust_id = f"BC-CUST-{name_prefix}-{phone_suffix}"
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        existing_cust = db.query(CustomerModel).filter(CustomerModel.phone == clean_phone).first()
        if existing_cust:
            existing_cust.name = customer.name
            existing_cust.email = customer.email or existing_cust.email
            if customer.password:
                existing_cust.password_hash = hash_password(customer.password)
            existing_cust.city = customer.city or existing_cust.city
            existing_cust.state = customer.state or existing_cust.state
            existing_cust.pincode = customer.pincode or existing_cust.pincode
            existing_cust.updated_at = now_str
            cust_id = existing_cust.customer_id
            db.commit()
            print(f"Updated customer profile for {customer.name} (ID: {cust_id}).")
        else:
            cust_id = generated_cust_id
            new_cust = CustomerModel(
                customer_id=cust_id,
                name=customer.name,
                phone=clean_phone,
                email=customer.email or None,
                password_hash=hash_password(customer.password) if customer.password else None,
                city=customer.city or None,
                state=customer.state or None,
                pincode=customer.pincode or None,
                created_at=now_str,
                updated_at=now_str
            )
            db.add(new_cust)
            db.commit()
            print(f"Created customer profile for {customer.name} (ID: {cust_id}).")

        return {"status": "success", "message": "Customer details stored successfully", "customer_id": cust_id}
    except Exception as e:
        db.rollback()
        print(f"Error saving customer to DB: {e}")
        raise HTTPException(status_code=500, detail="Failed to save customer details.")

@app.post("/customers/register")
def register_customer(req: CustomerRegisterRequest, db: Session = Depends(get_db)):
    """Register a new customer with hashed password in the customers table."""
    clean_phone = clean_phone_to_10_digits(req.phone)
    if len(clean_phone) != 10:
        raise HTTPException(status_code=400, detail="A valid 10-digit phone number is required.")
    
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    existing_phone = db.query(CustomerModel).filter(CustomerModel.phone == clean_phone).first()
    if existing_phone:
        raise HTTPException(status_code=400, detail="An account with this phone number already exists.")

    if req.email:
        existing_email = db.query(CustomerModel).filter(CustomerModel.email == req.email.strip().lower()).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="An account with this email already exists.")

    phone_suffix = clean_phone[-4:]
    name_clean = "".join(filter(str.isalpha, req.name)).upper()
    name_prefix = name_clean[:3] if len(name_clean) >= 3 else "CST"
    cust_id = f"BC-CUST-{name_prefix}-{phone_suffix}"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        new_customer = CustomerModel(
            customer_id=cust_id,
            name=req.name.strip(),
            phone=clean_phone,
            email=req.email.strip().lower() if req.email else None,
            password_hash=hash_password(req.password),
            created_at=now_str,
            updated_at=now_str
        )
        db.add(new_customer)
        db.commit()
        db.refresh(new_customer)

        return {
            "status": "success",
            "message": "Customer account created successfully",
            "customer": {
                "id": new_customer.customer_id,
                "name": new_customer.name,
                "phone": new_customer.phone,
                "email": new_customer.email
            }
        }
    except Exception as e:
        db.rollback()
        print(f"Error registering customer: {e}")
        raise HTTPException(status_code=500, detail="Failed to register customer.")

@app.post("/customers/login")
def login_customer(req: CustomerLoginRequest, db: Session = Depends(get_db)):
    """Authenticate customer against the customers table via email or phone."""
    trimmed_id = req.identifier.strip()
    is_email = "@" in trimmed_id

    customer = None
    if is_email:
        customer = db.query(CustomerModel).filter(CustomerModel.email == trimmed_id.lower()).first()
    else:
        clean_phone = clean_phone_to_10_digits(trimmed_id)
        customer = db.query(CustomerModel).filter(CustomerModel.phone == clean_phone).first()

    if not customer or not customer.password_hash:
        raise HTTPException(status_code=401, detail="Invalid credentials or user not found.")

    if not verify_password(req.password, customer.password_hash):
        raise HTTPException(status_code=401, detail="Invalid password.")

    return {
        "status": "success",
        "message": "Login successful",
        "customer": {
            "id": customer.customer_id,
            "name": customer.name,
            "phone": customer.phone,
            "email": customer.email,
            "city": customer.city,
            "pincode": customer.pincode
        }
    }

@app.post("/customers/forgot-password")
def forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Look up customer by email or phone, generate reset token, and send reset email."""
    trimmed_id = req.identifier.strip()
    if not trimmed_id:
        raise HTTPException(status_code=400, detail="Email or phone number is required.")

    is_email = "@" in trimmed_id
    customer = None
    if is_email:
        customer = db.query(CustomerModel).filter(CustomerModel.email == trimmed_id.lower()).first()
    else:
        clean_phone = clean_phone_to_10_digits(trimmed_id)
        customer = db.query(CustomerModel).filter(CustomerModel.phone == clean_phone).first()

    if not customer:
        raise HTTPException(
            status_code=404,
            detail="No account found matching this email or phone number. Please check or register."
        )

    if not customer.email:
        raise HTTPException(
            status_code=400,
            detail="Your account doesn't have an email address associated with it. Please contact support or register a new account."
        )

    # Generate secure 32-byte URL-safe token
    token = secrets.token_urlsafe(32)
    expiry_time = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

    try:
        customer.reset_token = token
        customer.reset_token_expiry = expiry_time
        db.commit()

        reset_link = f"{FRONTEND_URL}/reset-password?token={token}"
        email_sent = send_reset_email(customer.email, customer.name, reset_link)

        # Mask email for privacy response e.g. j***@example.com
        parts = customer.email.split("@")
        masked_email = parts[0][0] + "***@" + parts[1] if len(parts) == 2 and len(parts[0]) > 1 else customer.email

        return {
            "status": "success",
            "message": f"Password reset link has been sent to {masked_email}.",
            "email": masked_email,
            "debug_link": reset_link if not SMTP_PASSWORD else None
        }
    except Exception as e:
        db.rollback()
        print(f"Error handling forgot password: {e}")
        raise HTTPException(status_code=500, detail="Failed to process password reset request.")

@app.get("/customers/verify-reset-token")
def verify_reset_token(token: str, db: Session = Depends(get_db)):
    """Validate whether a password reset token is valid and not expired."""
    if not token:
        raise HTTPException(status_code=400, detail="Token is required.")

    customer = db.query(CustomerModel).filter(CustomerModel.reset_token == token.strip()).first()
    if not customer or not customer.reset_token_expiry:
        raise HTTPException(status_code=400, detail="Invalid or expired password reset link.")

    try:
        expiry_dt = datetime.strptime(customer.reset_token_expiry, "%Y-%m-%d %H:%M:%S")
        if datetime.now() > expiry_dt:
            raise HTTPException(status_code=400, detail="This reset link has expired. Please request a new one.")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid token expiry.")

    return {
        "status": "success",
        "valid": True,
        "name": customer.name,
        "email": customer.email
    }

@app.post("/customers/reset-password")
def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset customer password using a valid reset token."""
    token = req.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token is required.")

    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    customer = db.query(CustomerModel).filter(CustomerModel.reset_token == token).first()
    if not customer or not customer.reset_token_expiry:
        raise HTTPException(status_code=400, detail="Invalid or expired password reset link.")

    try:
        expiry_dt = datetime.strptime(customer.reset_token_expiry, "%Y-%m-%d %H:%M:%S")
        if datetime.now() > expiry_dt:
            raise HTTPException(status_code=400, detail="This reset link has expired. Please request a new one.")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid token expiry format.")

    try:
        customer.password_hash = hash_password(req.new_password)
        customer.reset_token = None
        customer.reset_token_expiry = None
        customer.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.commit()

        return {
            "status": "success",
            "message": "Password updated successfully. You can now log in with your new password."
        }
    except Exception as e:
        db.rollback()
        print(f"Error resetting password: {e}")
        raise HTTPException(status_code=500, detail="Failed to update password.")

@app.get("/customers/{customer_id}/orders")
def get_customer_orders(customer_id: str, db: Session = Depends(get_db)):
    """Retrieve all historical orders for a specific customer by customer_id or phone."""
    cid = customer_id.strip()
    try:
        # Also resolve customer by customer_id to ensure we find matching orders even if mapped by phone
        cust = db.query(CustomerModel).filter(CustomerModel.customer_id == cid).first()
        
        # Query orders matching either customer_id or customer's phone
        query = db.query(OrderModel)
        if cust and cust.phone:
            orders = query.filter((OrderModel.customer_id == cid) | (OrderModel.phone == cust.phone)).order_by(OrderModel.id.desc()).all()
        else:
            orders = query.filter(OrderModel.customer_id == cid).order_by(OrderModel.id.desc()).all()

        result = []
        for o in orders:
            result.append({
                "order_id": o.order_id,
                "customer_id": o.customer_id,
                "name": o.name,
                "phone": o.phone,
                "email": o.email,
                "addressLine1": o.addressLine1,
                "landmark": o.landmark,
                "city": o.city,
                "pincode": o.pincode,
                "date": o.date,
                "timeSlot": o.timeSlot,
                "occasion": o.occasion,
                "customOccasion": o.customOccasion,
                "items_summary": o.items_summary,
                "activePromo": o.activePromo,
                "discountAmount": o.discountAmount,
                "totalAmount": o.totalAmount,
                "status": o.status or "order_confirmed",
                "created_at": o.created_at
            })
        return result
    except Exception as e:
        print(f"Error retrieving orders for customer {customer_id}: {e}")
        return []

@app.patch("/orders/{order_id}/status")
def update_order_status(order_id: str, req: OrderStatusUpdate, db: Session = Depends(get_db)):
    """Update order status (e.g. order_confirmed, dispatched, shipped, delivered, cancelled)."""
    valid_statuses = ["order_confirmed", "dispatched", "shipped", "delivered", "cancelled"]
    normalized_status = req.status.strip().lower().replace(" ", "_")
    if normalized_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed values: {valid_statuses}")

    order = db.query(OrderModel).filter(OrderModel.order_id == order_id.strip()).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    try:
        order.status = normalized_status
        db.commit()
        db.refresh(order)
        return {
            "status": "success",
            "order_id": order.order_id,
            "new_status": order.status,
            "message": f"Order status updated to '{order.status}'"
        }
    except Exception as e:
        db.rollback()
        print(f"Error updating order status: {e}")
        raise HTTPException(status_code=500, detail="Failed to update order status.")


# ============================================================================
# Delivery / Shipping Endpoints
# ============================================================================

@app.get("/admin/shipping/providers")
def list_shipping_providers():
    """List all available shipping providers and their configuration status."""
    return get_available_providers()


@app.post("/admin/orders/{order_id}/delivery-quote")
async def get_delivery_quote(order_id: str, req: DeliveryQuoteRequest, db: Session = Depends(get_db)):
    """Get a delivery price quote from a shipping provider for an order."""
    order = db.query(OrderModel).filter(OrderModel.order_id == order_id.strip()).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    try:
        provider = get_shipping_provider(req.provider)
        pickup = get_pickup_address()
        delivery_addr = Address(
            address_line=order.addressLine1 or "",
            city=order.city or "",
            pincode=order.pincode or "",
            landmark=order.landmark,
            contact_name=order.name,
            contact_phone=order.phone,
        )

        quote = await provider.get_quote(pickup, delivery_addr, f"Cake order {order_id}")
        return {
            "provider": quote.provider,
            "estimated_price": quote.estimated_price,
            "currency": quote.currency,
            "estimated_duration_minutes": quote.estimated_duration_minutes,
            "vehicle_type": quote.vehicle_type,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error getting delivery quote: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get delivery quote: {str(e)}")


@app.post("/admin/orders/{order_id}/dispatch")
async def dispatch_delivery(order_id: str, req: DeliveryDispatchRequest, db: Session = Depends(get_db)):
    """Create a delivery dispatch with the selected shipping provider."""
    order = db.query(OrderModel).filter(OrderModel.order_id == order_id.strip()).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    # Check if delivery already exists for this order
    existing_delivery = db.query(DeliveryModel).filter(
        DeliveryModel.order_id == order_id.strip(),
        DeliveryModel.status.notin_(["cancelled", "failed"])
    ).first()
    if existing_delivery:
        raise HTTPException(status_code=400, detail=f"Active delivery already exists for this order (ID: {existing_delivery.delivery_id}, Status: {existing_delivery.status})")

    try:
        provider = get_shipping_provider(req.provider)
        pickup = get_pickup_address()
        delivery_addr = Address(
            address_line=order.addressLine1 or "",
            city=order.city or "",
            pincode=order.pincode or "",
            landmark=order.landmark,
            contact_name=order.name,
            contact_phone=order.phone,
        )

        result = await provider.create_delivery(
            pickup=pickup,
            delivery=delivery_addr,
            order_id=order_id,
            package_description=req.package_description or f"BloomCakes order {order_id}",
            package_value=float(order.totalAmount or 0),
        )

        # Generate delivery ID
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        delivery_id = f"BC-DLV-{order_id.replace('BC-ORD-', '')}-{datetime.now().strftime('%H%M%S')}"

        pickup_str = f"{pickup.address_line}, {pickup.city}, {pickup.pincode}"
        delivery_str = f"{delivery_addr.address_line}, {delivery_addr.city}, {delivery_addr.pincode}"

        new_delivery = DeliveryModel(
            delivery_id=delivery_id,
            order_id=order_id,
            provider=result.provider,
            provider_order_id=result.provider_order_id,
            pickup_address=pickup_str,
            delivery_address=delivery_str,
            delivery_fee=result.estimated_price,
            currency=result.currency,
            tracking_url=result.tracking_url,
            rider_name=result.rider_name,
            rider_phone=result.rider_phone,
            status=result.status,
            provider_status_raw=json.dumps(result.raw_response) if result.raw_response else None,
            created_at=now_str,
            updated_at=now_str,
        )
        db.add(new_delivery)

        # Update order status to dispatched
        mapped_order_status = DELIVERY_TO_ORDER_STATUS.get(result.status, "dispatched")
        if order.status in ("order_confirmed", "dispatched"):
            order.status = mapped_order_status

        db.commit()
        db.refresh(new_delivery)

        print(f"Delivery dispatched: {delivery_id} via {result.provider} for order {order_id}")

        return {
            "status": "success",
            "delivery_id": delivery_id,
            "provider": result.provider,
            "provider_order_id": result.provider_order_id,
            "delivery_status": result.status,
            "estimated_price": result.estimated_price,
            "tracking_url": result.tracking_url,
            "rider_name": result.rider_name,
            "rider_phone": result.rider_phone,
            "order_status": order.status,
            "message": f"Delivery dispatched successfully via {result.provider}"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        print(f"Error dispatching delivery: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to dispatch delivery: {str(e)}")


@app.get("/admin/orders/{order_id}/delivery")
async def get_delivery_info(order_id: str, db: Session = Depends(get_db)):
    """Get delivery information for an order, including live status from provider."""
    delivery = db.query(DeliveryModel).filter(
        DeliveryModel.order_id == order_id.strip()
    ).order_by(DeliveryModel.id.desc()).first()

    if not delivery:
        return {"has_delivery": False, "delivery": None}

    # If delivery is active, try to get live status from provider
    live_status = None
    if delivery.status not in ("delivered", "cancelled", "failed") and delivery.provider != "manual":
        try:
            provider = get_shipping_provider(delivery.provider)
            if delivery.provider_order_id:
                live_status = await provider.get_delivery_status(delivery.provider_order_id)
                # Update local DB with latest status
                if live_status:
                    delivery.status = live_status.status
                    delivery.rider_name = live_status.rider_name or delivery.rider_name
                    delivery.rider_phone = live_status.rider_phone or delivery.rider_phone
                    delivery.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    delivery.provider_status_raw = json.dumps(live_status.raw_response) if live_status.raw_response else delivery.provider_status_raw
                    db.commit()
                    db.refresh(delivery)
        except Exception as e:
            print(f"Could not fetch live status for delivery {delivery.delivery_id}: {e}")

    return {
        "has_delivery": True,
        "delivery": {
            "delivery_id": delivery.delivery_id,
            "order_id": delivery.order_id,
            "provider": delivery.provider,
            "provider_order_id": delivery.provider_order_id,
            "pickup_address": delivery.pickup_address,
            "delivery_address": delivery.delivery_address,
            "delivery_fee": delivery.delivery_fee,
            "currency": delivery.currency,
            "tracking_url": delivery.tracking_url,
            "rider_name": delivery.rider_name,
            "rider_phone": delivery.rider_phone,
            "status": delivery.status,
            "created_at": delivery.created_at,
            "updated_at": delivery.updated_at,
        }
    }


@app.post("/admin/orders/{order_id}/cancel-delivery")
async def cancel_order_delivery(order_id: str, db: Session = Depends(get_db)):
    """Cancel an active delivery for an order."""
    delivery = db.query(DeliveryModel).filter(
        DeliveryModel.order_id == order_id.strip(),
        DeliveryModel.status.notin_(["delivered", "cancelled", "failed"])
    ).order_by(DeliveryModel.id.desc()).first()

    if not delivery:
        raise HTTPException(status_code=404, detail="No active delivery found for this order.")

    try:
        # Cancel with provider if not manual
        if delivery.provider != "manual" and delivery.provider_order_id:
            provider = get_shipping_provider(delivery.provider)
            success = await provider.cancel_delivery(delivery.provider_order_id)
            if not success:
                raise HTTPException(status_code=400, detail="Provider could not cancel this delivery. It may already be picked up.")

        delivery.status = "cancelled"
        delivery.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Revert order status if it was dispatched
        order = db.query(OrderModel).filter(OrderModel.order_id == order_id.strip()).first()
        if order and order.status in ("dispatched", "shipped"):
            order.status = "order_confirmed"

        db.commit()

        return {
            "status": "success",
            "delivery_id": delivery.delivery_id,
            "message": "Delivery cancelled successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"Error cancelling delivery: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel delivery: {str(e)}")


@app.get("/admin/deliveries")
def get_all_deliveries(db: Session = Depends(get_db)):
    """Get all delivery records for the admin dashboard."""
    try:
        deliveries = db.query(DeliveryModel).order_by(DeliveryModel.id.desc()).all()
        return [
            {
                "delivery_id": d.delivery_id,
                "order_id": d.order_id,
                "provider": d.provider,
                "provider_order_id": d.provider_order_id,
                "pickup_address": d.pickup_address,
                "delivery_address": d.delivery_address,
                "delivery_fee": d.delivery_fee,
                "tracking_url": d.tracking_url,
                "rider_name": d.rider_name,
                "rider_phone": d.rider_phone,
                "status": d.status,
                "created_at": d.created_at,
                "updated_at": d.updated_at,
            }
            for d in deliveries
        ]
    except Exception as e:
        print(f"Error fetching deliveries: {e}")
        return []


@app.post("/webhooks/delivery/{provider_name}")
async def delivery_webhook(provider_name: str, payload: dict, db: Session = Depends(get_db)):
    """Receive real-time delivery status updates from shipping providers via webhook."""
    try:
        provider = get_shipping_provider(provider_name)
        status_update = provider.parse_webhook(payload)

        if not status_update or not status_update.provider_order_id:
            return {"status": "ignored", "message": "Could not parse webhook payload"}

        # Find the delivery record
        delivery = db.query(DeliveryModel).filter(
            DeliveryModel.provider_order_id == status_update.provider_order_id
        ).first()

        if not delivery:
            print(f"Webhook: No delivery found for provider order {status_update.provider_order_id}")
            return {"status": "not_found"}

        # Update delivery status
        delivery.status = status_update.status
        delivery.rider_name = status_update.rider_name or delivery.rider_name
        delivery.rider_phone = status_update.rider_phone or delivery.rider_phone
        delivery.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        delivery.provider_status_raw = json.dumps(status_update.raw_response) if status_update.raw_response else delivery.provider_status_raw

        # Auto-update order status based on delivery status
        order = db.query(OrderModel).filter(OrderModel.order_id == delivery.order_id).first()
        if order:
            new_order_status = DELIVERY_TO_ORDER_STATUS.get(status_update.status)
            if new_order_status and order.status != "cancelled":
                order.status = new_order_status

        db.commit()

        print(f"Webhook: Updated delivery {delivery.delivery_id} to status '{status_update.status}'")
        return {"status": "success", "delivery_id": delivery.delivery_id, "new_status": status_update.status}

    except Exception as e:
        db.rollback()
        print(f"Webhook processing error: {e}")
        return {"status": "error", "message": str(e)}


@app.patch("/admin/deliveries/{delivery_id}/status")
def update_delivery_status_manual(delivery_id: str, req: OrderStatusUpdate, db: Session = Depends(get_db)):
    """Manually update a delivery status (mainly for manual/self deliveries)."""
    valid_statuses = ["pending", "accepted", "rider_assigned", "picked_up", "in_transit", "delivered", "cancelled", "failed"]
    normalized = req.status.strip().lower().replace(" ", "_")
    if normalized not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid delivery status. Allowed: {valid_statuses}")

    delivery = db.query(DeliveryModel).filter(DeliveryModel.delivery_id == delivery_id.strip()).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found.")

    try:
        delivery.status = normalized
        delivery.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Auto-update order status
        order = db.query(OrderModel).filter(OrderModel.order_id == delivery.order_id).first()
        if order:
            new_order_status = DELIVERY_TO_ORDER_STATUS.get(normalized)
            if new_order_status and order.status != "cancelled":
                order.status = new_order_status

        db.commit()
        return {
            "status": "success",
            "delivery_id": delivery.delivery_id,
            "new_status": delivery.status,
            "message": f"Delivery status updated to '{normalized}'"
        }
    except Exception as e:
        db.rollback()
        print(f"Error updating delivery status: {e}")
        raise HTTPException(status_code=500, detail="Failed to update delivery status.")



@app.post("/api/create-order")
def create_razorpay_order(req: CreateOrderRequest):
    """Create order record identifier in Razorpay gateway client."""
    if not razorpay_client:
        raise HTTPException(status_code=401, detail="Razorpay credentials not initialized.")
    
    if req.amount < 100:
        raise HTTPException(status_code=400, detail="Minimum amount must be 100 paise.")

    try:
        order_data = {
            "amount": req.amount,
            "currency": req.currency,
            "receipt": req.receipt or "rcpt_bloomcakes",
            "payment_capture": 1
        }
        order = razorpay_client.order.create(data=order_data)
        return {
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"]
        }
    except Exception as e:
        print(f"Razorpay API Error: {e}")
        raise HTTPException(status_code=500, detail=f"Razorpay API Order creation failed: {str(e)}")

@app.post("/api/verify-payment")
def verify_payment_signature(req: VerifyPaymentRequest):
    """Verify cryptographic validity of payment signature generated client-side."""
    if not RAZORPAY_KEY_SECRET:
        raise HTTPException(status_code=401, detail="Razorpay secret key configurations unavailable.")

    msg = f"{req.razorpay_order_id}|{req.razorpay_payment_id}"
    
    try:
        generated_signature = hmac.new(
            key=RAZORPAY_KEY_SECRET.encode("utf-8"),
            msg=msg.encode("utf-8"),
            digestmod=hashlib.sha256
        ).hexdigest()

        if generated_signature == req.razorpay_signature:
            return {"status": "success", "message": "Payment signature verified successfully"}
        else:
            raise HTTPException(status_code=400, detail="Signature mismatch validation error")
    except Exception as e:
        print(f"Verification Failure: {e}")
        raise HTTPException(status_code=400, detail=str(e))
