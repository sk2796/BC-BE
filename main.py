import os
import hmac
import hashlib
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
import razorpay
from dotenv import load_dotenv

try:
    from backend.database import engine, Base, get_db
    from backend.models import ProductModel, PincodeModel, OrderModel, CustomerModel
except ImportError:
    from database import engine, Base, get_db
    from models import ProductModel, PincodeModel, OrderModel, CustomerModel

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
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None


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
    return {"serviceable": False, "city": None, "state": None}

@app.get("/admin/orders")
def get_all_orders(db: Session = Depends(get_db)):
    """Retrieve all saved order records from MySQL Database."""
    try:
        orders = db.query(OrderModel).order_by(OrderModel.id.desc()).all()
        result = []
        for o in orders:
            result.append({
                "order_id": o.order_id,
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
    """Save order record to MySQL Database."""
    clean_phone = clean_phone_to_10_digits(order.phone)
    phone_suffix = clean_phone[-4:] if len(clean_phone) >= 4 else "0000"
    
    order_id = f"BC-ORD-{phone_suffix}-{order.date.replace('-', '')}"
    items_summary = ", ".join([f"{item.name} ({item.weight}) x{item.quantity}" for item in order.items])
    
    try:
        new_order = OrderModel(
            order_id=order_id,
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
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        db.add(new_order)
        db.commit()
        db.refresh(new_order)
        print(f"Stored order {order_id} to MySQL DB.")
    except Exception as e:
        db.rollback()
        print(f"Error saving order to DB: {e}")
        raise HTTPException(status_code=500, detail="Failed to save order to database.")

    return {
        "status": "success",
        "order_id": order_id,
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
                city=customer.city or None,
                state=customer.state or None,
                pincode=customer.pincode or None,
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
