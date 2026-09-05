from sqlalchemy import Column, String, Integer, Float, Boolean, Text
from datetime import datetime
try:
    from backend.database import Base
except ImportError:
    from database import Base

class ProductModel(Base):
    __tablename__ = "products"

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Integer, nullable=False)
    category = Column(String(100), nullable=False)
    imageUrl = Column(Text, nullable=False)
    isBestseller = Column(Boolean, default=False)
    rating = Column(Float, default=5.0)

class PincodeModel(Base):
    __tablename__ = "pincodes"

    pincode = Column(String(20), primary_key=True, index=True)
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=False)

class OrderModel(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100), index=True, nullable=False)
    name = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=False, index=True)
    email = Column(String(255), nullable=True)
    addressLine1 = Column(Text, nullable=False)
    landmark = Column(Text, nullable=True)
    city = Column(String(100), nullable=False)
    pincode = Column(String(20), nullable=False)
    date = Column(String(50), nullable=False)
    timeSlot = Column(String(100), nullable=False)
    occasion = Column(String(100), nullable=False)
    customOccasion = Column(String(255), nullable=True)
    items_summary = Column(Text, nullable=False)
    activePromo = Column(String(100), nullable=True)
    discountAmount = Column(Integer, default=0)
    totalAmount = Column(Integer, nullable=False)
    created_at = Column(String(50), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

class CustomerModel(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String(100), index=True, nullable=False)
    name = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    pincode = Column(String(20), nullable=True)
    updated_at = Column(String(50), default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
