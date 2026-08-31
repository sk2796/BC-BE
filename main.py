import os
import hmac
import hashlib
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import pandas as pd
import razorpay
from dotenv import load_dotenv

# Load credentials from .env configurations file
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

# Initialize Razorpay Client wrapper
razorpay_client = None
if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

app = FastAPI(
    title="BloomCakes Backend API",
    description="Lightweight backend APIs reading mock products data from Excel sheets",
    version="1.0.0"
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXCEL_FILE_PATH = os.path.join(os.path.dirname(__file__), "products.xlsx")
PINCODES_FILE_PATH = os.path.join(os.path.dirname(__file__), "pincodes.xlsx")
ORDERS_EXCEL_FILE_PATH = os.path.join(os.path.dirname(__file__), "orders.xlsx")
CUSTOMERS_EXCEL_FILE_PATH = os.path.join(os.path.dirname(__file__), "customers.xlsx")

# Mock databases models representation
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

class PincodeItem(BaseModel):
    pincode: str
    city: str

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

def read_products_from_excel() -> List[dict]:
    """Helper method to load product rows dynamically from local Excel database."""
    if not os.path.exists(EXCEL_FILE_PATH):
        return []
    try:
        df = pd.read_excel(EXCEL_FILE_PATH)
        # Standardize NaN values to None for clean JSON outputs representation
        df = df.where(pd.notnull(df), None)
        return df.to_dict(orient="records")
    except Exception as e:
        print(f"Error reading Excel sheet: {e}")
        return []

def read_pincodes_from_excel() -> List[dict]:
    """Helper method to load pincodes and associated cities dynamically from local Excel database."""
    if not os.path.exists(PINCODES_FILE_PATH):
        return []
    try:
        df = pd.read_excel(PINCODES_FILE_PATH)
        df['pincode'] = df['pincode'].astype(str)
        # Standardize NaN values to None for clean JSON outputs representation
        df = df.where(pd.notnull(df), None)
        return df.to_dict(orient="records")
    except Exception as e:
        print(f"Error reading pincodes Excel sheet: {e}")
        return []

@app.get("/")
def read_root():
    return {"message": "Welcome to BloomCakes Backend API. Visit /docs for Swagger specifications documentation."}

@app.get("/pincodes")
def check_pincode(code: str):
    """Check if a specific pincode is serviceable by searching the Excel sheet."""
    pincodes = read_pincodes_from_excel()
    for item in pincodes:
        if item.get("pincode") == code.strip():
            return {"serviceable": True, "city": item.get("city"), "state": item.get("state")}
    return {"serviceable": False, "city": None, "state": None}

@app.get("/products", response_model=List[CakeItem])
def get_products():
    """Retrieve all cake catalog items from the Excel sheet."""
    products = read_products_from_excel()
    if not products:
        raise HTTPException(status_code=404, detail="No products found in database.")
    return products

@app.get("/products/{slug}", response_model=CakeItem)
def get_product_by_slug(slug: str):
    """Retrieve a single cake product matched by its unique slug from the Excel database."""
    products = read_products_from_excel()
    for prod in products:
        if prod.get("slug") == slug:
            return prod
    raise HTTPException(status_code=404, detail="Product not found.")

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

    # Format verification message payload data
    msg = f"{req.razorpay_order_id}|{req.razorpay_payment_id}"
    
    try:
        # Generate hash verification signatures
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

def clean_phone_to_10_digits(phone: str) -> str:
    # Remove all non-digit characters
    digits = "".join(filter(str.isdigit, str(phone)))
    # If it starts with 91 and has 12 digits, strip the leading 91
    if len(digits) == 12 and digits.startswith("91"):
        return digits[2:]
    # Otherwise, return the last 10 digits if it's longer
    if len(digits) >= 10:
        return digits[-10:]
    return digits

@app.post("/orders")
def submit_order(order: OrderSubmission):
    # Clean phone number to exactly 10 digits
    clean_phone = clean_phone_to_10_digits(order.phone)
    phone_suffix = clean_phone[-4:] if len(clean_phone) >= 4 else "0000"
    
    # Generate order ID
    order_id = f"BC-ORD-{phone_suffix}-{order.date.replace('-', '')}"
    
    # Format items list to a human-readable summary
    items_summary = ", ".join([f"{item.name} ({item.weight}) x{item.quantity}" for item in order.items])
    
    from datetime import datetime
    new_order_data = {
        "order_id": order_id,
        "name": order.name,
        "phone": clean_phone,
        "email": order.email or "",
        "addressLine1": order.addressLine1,
        "landmark": order.landmark or "",
        "city": order.city,
        "pincode": order.pincode,
        "date": order.date,
        "timeSlot": order.timeSlot,
        "occasion": order.occasion,
        "customOccasion": order.customOccasion or "",
        "items_summary": items_summary,
        "activePromo": order.activePromo or "",
        "discountAmount": order.discountAmount,
        "totalAmount": order.totalAmount,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Load existing orders or create new DataFrame and save to Excel
    try:
        if os.path.exists(ORDERS_EXCEL_FILE_PATH):
            df = pd.read_excel(ORDERS_EXCEL_FILE_PATH)
            # Clean existing phone records in DF
            df['phone'] = df['phone'].apply(lambda x: clean_phone_to_10_digits(str(x)))
            new_row_df = pd.DataFrame([new_order_data])
            df = pd.concat([df, new_row_df], ignore_index=True)
        else:
            df = pd.DataFrame([new_order_data])
            
        df.to_excel(ORDERS_EXCEL_FILE_PATH, index=False)
        print(f"Stored order {order_id} to Excel.")
    except Exception as e:
        print(f"Error saving order to Excel: {e}")
        raise HTTPException(status_code=500, detail="Failed to save order to database sheet.")

    return {
        "status": "success",
        "order_id": order_id,
        "message": "Order processed and stored successfully"
    }

@app.post("/customers")
def save_customer(customer: CustomerDetails):
    """Save customer contact details profile in a separate Excel spreadsheet database."""
    from datetime import datetime
    
    clean_phone = clean_phone_to_10_digits(customer.phone)
    
    # Generate customer ID template
    phone_suffix = clean_phone[-4:] if len(clean_phone) >= 4 else "0000"
    name_clean = "".join(filter(str.isalpha, customer.name)).upper()
    name_prefix = name_clean[:3] if len(name_clean) >= 3 else "CST"
    generated_cust_id = f"BC-CUST-{name_prefix}-{phone_suffix}"

    new_cust_data = {
        "customer_id": generated_cust_id,
        "name": customer.name,
        "phone": clean_phone,
        "email": customer.email or "",
        "city": customer.city or "",
        "state": customer.state or "",
        "pincode": customer.pincode or "",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    try:
        if os.path.exists(CUSTOMERS_EXCEL_FILE_PATH):
            df = pd.read_excel(CUSTOMERS_EXCEL_FILE_PATH)
            # Clean and stringify existing phone records for precise matches
            df['phone'] = df['phone'].apply(lambda x: clean_phone_to_10_digits(str(x)))
            
            existing_idx = df.index[df['phone'] == clean_phone].tolist()
            if existing_idx:
                # If they already have a customer_id, preserve it
                existing_row = df.loc[existing_idx[0]]
                cust_id = existing_row.get("customer_id")
                if pd.isna(cust_id) or not cust_id:
                    cust_id = generated_cust_id
                
                new_cust_data["customer_id"] = cust_id
                
                for col, val in new_cust_data.items():
                    df.loc[existing_idx[0], col] = val
            else:
                new_row_df = pd.DataFrame([new_cust_data])
                df = pd.concat([df, new_row_df], ignore_index=True)
        else:
            df = pd.DataFrame([new_cust_data])
            
        df.to_excel(CUSTOMERS_EXCEL_FILE_PATH, index=False)
        print(f"Saved customer profile for {customer.name} (ID: {new_cust_data['customer_id']}).")
    except Exception as e:
        print(f"Error saving customer to Excel: {e}")
        raise HTTPException(status_code=500, detail="Failed to save customer details.")
        
    return {"status": "success", "message": "Customer details stored successfully", "customer_id": new_cust_data["customer_id"]}
