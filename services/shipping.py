"""
BloomCakes Shipping Service Layer
==================================
Provider-agnostic abstraction for hyper-local delivery integrations.
Supports Borzo, Porter, and can be extended to any new provider.

Usage:
    from backend.services.shipping import get_shipping_provider
    provider = get_shipping_provider()
    quote = await provider.get_quote(pickup, delivery)
"""

import os
import json
import httpx
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass, asdict


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Address:
    """Represents a pickup or delivery address."""
    address_line: str
    city: str
    pincode: str
    landmark: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


@dataclass
class DeliveryQuote:
    """Price quote returned by a shipping provider."""
    provider: str
    estimated_price: float
    currency: str = "INR"
    estimated_duration_minutes: Optional[int] = None
    vehicle_type: Optional[str] = None
    quote_id: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


@dataclass
class DeliveryOrder:
    """Created delivery order from a shipping provider."""
    provider: str
    provider_order_id: str
    status: str
    estimated_price: float
    currency: str = "INR"
    tracking_url: Optional[str] = None
    rider_name: Optional[str] = None
    rider_phone: Optional[str] = None
    estimated_pickup_time: Optional[str] = None
    estimated_delivery_time: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


@dataclass
class DeliveryStatus:
    """Live status of a delivery order."""
    provider: str
    provider_order_id: str
    status: str  # pending, accepted, rider_assigned, picked_up, in_transit, delivered, cancelled, failed
    rider_name: Optional[str] = None
    rider_phone: Optional[str] = None
    rider_latitude: Optional[float] = None
    rider_longitude: Optional[float] = None
    updated_at: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Status mapping — normalize provider statuses to BloomCakes statuses
# ---------------------------------------------------------------------------

NORMALIZED_STATUS_MAP = {
    # BloomCakes internal → display name
    "pending": "Pending",
    "accepted": "Accepted",
    "rider_assigned": "Rider Assigned",
    "picked_up": "Picked Up",
    "in_transit": "In Transit",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
    "failed": "Failed",
    "returned": "Returned",
}

# Map normalized delivery statuses to order statuses
DELIVERY_TO_ORDER_STATUS = {
    "pending": "order_confirmed",
    "accepted": "order_confirmed",
    "rider_assigned": "dispatched",
    "picked_up": "shipped",
    "in_transit": "shipped",
    "delivered": "delivered",
    "cancelled": "order_confirmed",
    "failed": "order_confirmed",
    "returned": "order_confirmed",
}


# ---------------------------------------------------------------------------
# Abstract Base Provider
# ---------------------------------------------------------------------------

class ShippingProvider(ABC):
    """Abstract interface for a shipping/delivery provider."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g., 'borzo', 'porter')."""
        ...

    @abstractmethod
    async def check_serviceability(self, pickup: Address, delivery: Address) -> bool:
        """Check if delivery is possible between two addresses."""
        ...

    @abstractmethod
    async def get_quote(self, pickup: Address, delivery: Address, package_description: str = "") -> DeliveryQuote:
        """Get a delivery price quote."""
        ...

    @abstractmethod
    async def create_delivery(
        self,
        pickup: Address,
        delivery: Address,
        order_id: str,
        package_description: str = "",
        package_value: float = 0,
    ) -> DeliveryOrder:
        """Create a delivery/dispatch order with the provider."""
        ...

    @abstractmethod
    async def get_delivery_status(self, provider_order_id: str) -> DeliveryStatus:
        """Get real-time status of a delivery."""
        ...

    @abstractmethod
    async def cancel_delivery(self, provider_order_id: str) -> bool:
        """Cancel an active delivery. Returns True if successfully cancelled."""
        ...

    def parse_webhook(self, payload: Dict[str, Any]) -> Optional[DeliveryStatus]:
        """Parse a webhook callback from the provider. Override per provider."""
        return None


# ---------------------------------------------------------------------------
# Borzo (WeFast) Provider
# ---------------------------------------------------------------------------

BORZO_STATUS_MAP = {
    "new": "pending",
    "available": "pending",
    "active": "rider_assigned",
    "courier_departed": "picked_up",
    "courier_on_the_way": "in_transit",
    "delivered": "delivered",
    "finished": "delivered",
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "failed": "failed",
    "reactivated": "pending",
}


class BorzoProvider(ShippingProvider):
    """
    Borzo (formerly WeFast) delivery provider.
    API docs: https://borzodelivery.com/in (Business API section)
    
    Requires:
        BORZO_API_TOKEN — your business account API token
        BORZO_API_BASE — sandbox: https://robotapitest.borzodelivery.com, 
                         production: https://robotapi.borzodelivery.com
    """

    def __init__(self):
        self.api_token = os.getenv("BORZO_API_TOKEN", "")
        self.api_base = os.getenv("BORZO_API_BASE", "https://robotapitest.borzodelivery.com")  # sandbox by default

    @property
    def name(self) -> str:
        return "borzo"

    def _headers(self) -> Dict[str, str]:
        return {
            "X-DV-Auth-Token": self.api_token,
            "Content-Type": "application/json",
        }

    def _is_configured(self) -> bool:
        return bool(self.api_token)

    async def check_serviceability(self, pickup: Address, delivery: Address) -> bool:
        """Borzo doesn't have a dedicated serviceability endpoint; 
        we check via price calculation — if it returns a price, it's serviceable."""
        if not self._is_configured():
            return False
        try:
            quote = await self.get_quote(pickup, delivery)
            return quote.estimated_price > 0
        except Exception:
            return False

    async def get_quote(self, pickup: Address, delivery: Address, package_description: str = "") -> DeliveryQuote:
        if not self._is_configured():
            raise ValueError("Borzo API token not configured. Set BORZO_API_TOKEN in .env")

        payload = {
            "matter": package_description or "Cake delivery",
            "vehicle_type_id": 8,  # Motorbike (most common for local delivery)
            "points": [
                {
                    "address": f"{pickup.address_line}, {pickup.city}, {pickup.pincode}",
                    "contact_person": {
                        "name": pickup.contact_name or "BloomCakes",
                        "phone": pickup.contact_phone or "",
                    }
                },
                {
                    "address": f"{delivery.address_line}, {delivery.city}, {delivery.pincode}",
                    "contact_person": {
                        "name": delivery.contact_name or "",
                        "phone": delivery.contact_phone or "",
                    }
                }
            ]
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.api_base}/api/business/1.8/calculate-order",
                headers=self._headers(),
                json=payload
            )
            data = resp.json()

        if not data.get("is_successful"):
            error_msg = data.get("errors", [{}])
            raise ValueError(f"Borzo quote failed: {error_msg}")

        order_data = data.get("order", {})
        return DeliveryQuote(
            provider=self.name,
            estimated_price=float(order_data.get("payment_amount", 0)),
            currency="INR",
            estimated_duration_minutes=order_data.get("delivery_fee_amount"),
            vehicle_type="Motorbike",
            quote_id=None,
            raw_response=data,
        )

    async def create_delivery(
        self,
        pickup: Address,
        delivery: Address,
        order_id: str,
        package_description: str = "",
        package_value: float = 0,
    ) -> DeliveryOrder:
        if not self._is_configured():
            raise ValueError("Borzo API token not configured. Set BORZO_API_TOKEN in .env")

        payload = {
            "matter": package_description or f"Cake order {order_id}",
            "vehicle_type_id": 8,
            "insurance_amount": package_value if package_value > 0 else None,
            "points": [
                {
                    "address": f"{pickup.address_line}, {pickup.city}, {pickup.pincode}",
                    "contact_person": {
                        "name": pickup.contact_name or "BloomCakes",
                        "phone": pickup.contact_phone or "",
                    },
                    "note": f"BloomCakes pickup for order {order_id}"
                },
                {
                    "address": f"{delivery.address_line}, {delivery.city}, {delivery.pincode}",
                    "contact_person": {
                        "name": delivery.contact_name or "",
                        "phone": delivery.contact_phone or "",
                    },
                    "note": delivery.landmark or ""
                }
            ]
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.api_base}/api/business/1.8/create-order",
                headers=self._headers(),
                json=payload
            )
            data = resp.json()

        if not data.get("is_successful"):
            error_msg = data.get("errors", [{}])
            raise ValueError(f"Borzo order creation failed: {error_msg}")

        order_data = data.get("order", {})
        borzo_status = order_data.get("status", "new")

        # Extract courier (rider) info if assigned
        courier = order_data.get("courier", {}) or {}

        return DeliveryOrder(
            provider=self.name,
            provider_order_id=str(order_data.get("order_id", "")),
            status=BORZO_STATUS_MAP.get(borzo_status, "pending"),
            estimated_price=float(order_data.get("payment_amount", 0)),
            currency="INR",
            tracking_url=order_data.get("tracking_url"),
            rider_name=courier.get("name"),
            rider_phone=courier.get("phone"),
            raw_response=data,
        )

    async def get_delivery_status(self, provider_order_id: str) -> DeliveryStatus:
        if not self._is_configured():
            raise ValueError("Borzo API token not configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.api_base}/api/business/1.8/orders",
                headers=self._headers(),
                params={"order_id": provider_order_id}
            )
            data = resp.json()

        if not data.get("is_successful"):
            raise ValueError(f"Borzo status check failed: {data.get('errors')}")

        orders = data.get("orders", [])
        if not orders:
            raise ValueError(f"Borzo order {provider_order_id} not found")

        order_data = orders[0]
        borzo_status = order_data.get("status", "new")
        courier = order_data.get("courier", {}) or {}

        return DeliveryStatus(
            provider=self.name,
            provider_order_id=provider_order_id,
            status=BORZO_STATUS_MAP.get(borzo_status, "pending"),
            rider_name=courier.get("name"),
            rider_phone=courier.get("phone"),
            rider_latitude=courier.get("latitude"),
            rider_longitude=courier.get("longitude"),
            updated_at=datetime.now().isoformat(),
            raw_response=data,
        )

    async def cancel_delivery(self, provider_order_id: str) -> bool:
        if not self._is_configured():
            raise ValueError("Borzo API token not configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.api_base}/api/business/1.8/cancel-order",
                headers=self._headers(),
                json={"order_id": provider_order_id}
            )
            data = resp.json()

        return data.get("is_successful", False)

    def parse_webhook(self, payload: Dict[str, Any]) -> Optional[DeliveryStatus]:
        """Parse Borzo webhook callback."""
        if not payload:
            return None

        order_data = payload.get("order", payload)
        borzo_status = order_data.get("status", "")
        courier = order_data.get("courier", {}) or {}

        return DeliveryStatus(
            provider=self.name,
            provider_order_id=str(order_data.get("order_id", "")),
            status=BORZO_STATUS_MAP.get(borzo_status, "pending"),
            rider_name=courier.get("name"),
            rider_phone=courier.get("phone"),
            rider_latitude=courier.get("latitude"),
            rider_longitude=courier.get("longitude"),
            updated_at=datetime.now().isoformat(),
            raw_response=payload,
        )


# ---------------------------------------------------------------------------
# Porter Provider
# ---------------------------------------------------------------------------

PORTER_STATUS_MAP = {
    "quote_created": "pending",
    "order_placed": "pending",
    "order_accepted": "accepted",
    "driver_assigned": "rider_assigned",
    "driver_arrived_at_pickup": "rider_assigned",
    "picked_up": "picked_up",
    "order_started": "in_transit",
    "reached_destination": "in_transit",
    "delivered": "delivered",
    "order_ended": "delivered",
    "cancelled": "cancelled",
    "order_cancelled": "cancelled",
}


class PorterProvider(ShippingProvider):
    """
    Porter (porter.in) delivery provider.
    Enterprise API — requires contacting Porter team for credentials.
    
    Requires:
        PORTER_API_KEY — API key from Porter enterprise team
        PORTER_API_BASE — production: https://pfe-apigw-uat.porter.in  (UAT/sandbox)
    """

    def __init__(self):
        self.api_key = os.getenv("PORTER_API_KEY", "")
        self.api_base = os.getenv("PORTER_API_BASE", "https://pfe-apigw-uat.porter.in")

    @property
    def name(self) -> str:
        return "porter"

    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def _is_configured(self) -> bool:
        return bool(self.api_key)

    async def check_serviceability(self, pickup: Address, delivery: Address) -> bool:
        if not self._is_configured():
            return False
        try:
            quote = await self.get_quote(pickup, delivery)
            return quote.estimated_price > 0
        except Exception:
            return False

    async def get_quote(self, pickup: Address, delivery: Address, package_description: str = "") -> DeliveryQuote:
        if not self._is_configured():
            raise ValueError("Porter API key not configured. Set PORTER_API_KEY in .env")

        payload = {
            "pickup_details": {
                "lat": pickup.latitude or 0,
                "lng": pickup.longitude or 0,
                "address": {
                    "apartment_address": "",
                    "street_address1": pickup.address_line,
                    "street_address2": "",
                    "landmark": pickup.landmark or "",
                    "city": pickup.city,
                    "state": "",
                    "pincode": pickup.pincode,
                    "country": "India"
                }
            },
            "drop_details": {
                "lat": delivery.latitude or 0,
                "lng": delivery.longitude or 0,
                "address": {
                    "apartment_address": "",
                    "street_address1": delivery.address_line,
                    "street_address2": "",
                    "landmark": delivery.landmark or "",
                    "city": delivery.city,
                    "state": "",
                    "pincode": delivery.pincode,
                    "country": "India"
                }
            },
            "customer": {
                "name": pickup.contact_name or "BloomCakes",
                "mobile": {
                    "country_code": "+91",
                    "number": pickup.contact_phone or ""
                }
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.api_base}/v1/get_quote",
                headers=self._headers(),
                json=payload
            )
            data = resp.json()

        if resp.status_code != 200:
            raise ValueError(f"Porter quote failed: {data}")

        vehicles = data.get("vehicles", [])
        if not vehicles:
            raise ValueError("No vehicle options available from Porter")

        # Pick the first (cheapest) option
        best = vehicles[0]
        return DeliveryQuote(
            provider=self.name,
            estimated_price=float(best.get("fare", {}).get("minor_amount", 0)) / 100,
            currency="INR",
            estimated_duration_minutes=best.get("eta", {}).get("value"),
            vehicle_type=best.get("type", "bike"),
            quote_id=data.get("request_id"),
            raw_response=data,
        )

    async def create_delivery(
        self,
        pickup: Address,
        delivery: Address,
        order_id: str,
        package_description: str = "",
        package_value: float = 0,
    ) -> DeliveryOrder:
        if not self._is_configured():
            raise ValueError("Porter API key not configured")

        # First get a quote to determine pricing
        quote = await self.get_quote(pickup, delivery, package_description)

        payload = {
            "request_id": quote.quote_id or "",
            "delivery_instructions": {
                "instructions_list": [
                    {"type": "text", "description": package_description or f"Cake order {order_id}. Handle with care."}
                ]
            },
            "pickup_details": {
                "address": {
                    "apartment_address": "",
                    "street_address1": pickup.address_line,
                    "street_address2": "",
                    "landmark": pickup.landmark or "",
                    "city": pickup.city,
                    "state": "",
                    "pincode": pickup.pincode,
                    "country": "India"
                },
                "lat": pickup.latitude or 0,
                "lng": pickup.longitude or 0,
            },
            "drop_details": {
                "address": {
                    "apartment_address": "",
                    "street_address1": delivery.address_line,
                    "street_address2": "",
                    "landmark": delivery.landmark or "",
                    "city": delivery.city,
                    "state": "",
                    "pincode": delivery.pincode,
                    "country": "India"
                },
                "lat": delivery.latitude or 0,
                "lng": delivery.longitude or 0,
            },
            "customer": {
                "name": delivery.contact_name or "",
                "mobile": {
                    "country_code": "+91",
                    "number": delivery.contact_phone or ""
                }
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.api_base}/v1/orders/create",
                headers=self._headers(),
                json=payload
            )
            data = resp.json()

        if resp.status_code not in (200, 201):
            raise ValueError(f"Porter order creation failed: {data}")

        porter_order_id = data.get("order_id", "")
        status = data.get("status", "order_placed")
        driver = data.get("driver", {}) or {}

        return DeliveryOrder(
            provider=self.name,
            provider_order_id=str(porter_order_id),
            status=PORTER_STATUS_MAP.get(status, "pending"),
            estimated_price=quote.estimated_price,
            currency="INR",
            tracking_url=data.get("tracking_url"),
            rider_name=driver.get("name"),
            rider_phone=driver.get("mobile", {}).get("number"),
            raw_response=data,
        )

    async def get_delivery_status(self, provider_order_id: str) -> DeliveryStatus:
        if not self._is_configured():
            raise ValueError("Porter API key not configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.api_base}/v1/orders/{provider_order_id}",
                headers=self._headers()
            )
            data = resp.json()

        if resp.status_code != 200:
            raise ValueError(f"Porter status check failed: {data}")

        status = data.get("status", "")
        driver = data.get("driver", {}) or {}
        location = data.get("driver_location", {}) or {}

        return DeliveryStatus(
            provider=self.name,
            provider_order_id=provider_order_id,
            status=PORTER_STATUS_MAP.get(status, "pending"),
            rider_name=driver.get("name"),
            rider_phone=driver.get("mobile", {}).get("number"),
            rider_latitude=location.get("lat"),
            rider_longitude=location.get("lng"),
            updated_at=datetime.now().isoformat(),
            raw_response=data,
        )

    async def cancel_delivery(self, provider_order_id: str) -> bool:
        if not self._is_configured():
            raise ValueError("Porter API key not configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.api_base}/v1/orders/{provider_order_id}/cancel",
                headers=self._headers(),
                json={"reason": "Cancelled by merchant"}
            )

        return resp.status_code in (200, 204)

    def parse_webhook(self, payload: Dict[str, Any]) -> Optional[DeliveryStatus]:
        """Parse Porter webhook callback."""
        if not payload:
            return None

        status = payload.get("status", "")
        driver = payload.get("driver", {}) or {}
        location = payload.get("driver_location", {}) or {}

        return DeliveryStatus(
            provider=self.name,
            provider_order_id=str(payload.get("order_id", "")),
            status=PORTER_STATUS_MAP.get(status, "pending"),
            rider_name=driver.get("name"),
            rider_phone=driver.get("mobile", {}).get("number"),
            rider_latitude=location.get("lat"),
            rider_longitude=location.get("lng"),
            updated_at=datetime.now().isoformat(),
            raw_response=payload,
        )


# ---------------------------------------------------------------------------
# Manual / Self-Delivery Provider (default fallback)
# ---------------------------------------------------------------------------

class ManualProvider(ShippingProvider):
    """
    Fallback provider for manual/self-delivery.
    Used when no third-party provider is configured.
    Allows admin to track deliveries manually through the dashboard.
    """

    @property
    def name(self) -> str:
        return "manual"

    async def check_serviceability(self, pickup: Address, delivery: Address) -> bool:
        return True

    async def get_quote(self, pickup: Address, delivery: Address, package_description: str = "") -> DeliveryQuote:
        return DeliveryQuote(
            provider=self.name,
            estimated_price=0,
            currency="INR",
            estimated_duration_minutes=None,
            vehicle_type="Self/Manual",
            quote_id=None,
            raw_response={"message": "Manual delivery — no third-party provider cost"},
        )

    async def create_delivery(
        self,
        pickup: Address,
        delivery: Address,
        order_id: str,
        package_description: str = "",
        package_value: float = 0,
    ) -> DeliveryOrder:
        return DeliveryOrder(
            provider=self.name,
            provider_order_id=f"MANUAL-{order_id}-{datetime.now().strftime('%H%M%S')}",
            status="rider_assigned",
            estimated_price=0,
            currency="INR",
            tracking_url=None,
            rider_name=None,
            rider_phone=None,
            raw_response={"message": "Manual dispatch created. Update status manually."},
        )

    async def get_delivery_status(self, provider_order_id: str) -> DeliveryStatus:
        return DeliveryStatus(
            provider=self.name,
            provider_order_id=provider_order_id,
            status="pending",
            updated_at=datetime.now().isoformat(),
            raw_response={"message": "Manual delivery — update status through admin dashboard"},
        )

    async def cancel_delivery(self, provider_order_id: str) -> bool:
        return True


# ---------------------------------------------------------------------------
# Provider Factory
# ---------------------------------------------------------------------------

# Pickup address configured via environment variables
def get_pickup_address() -> Address:
    """Get the default BloomCakes pickup address from env config."""
    return Address(
        address_line=os.getenv("PICKUP_ADDRESS", "BloomCakes Kitchen"),
        city=os.getenv("PICKUP_CITY", ""),
        pincode=os.getenv("PICKUP_PINCODE", ""),
        landmark=os.getenv("PICKUP_LANDMARK", ""),
        contact_name=os.getenv("PICKUP_CONTACT_NAME", "BloomCakes"),
        contact_phone=os.getenv("PICKUP_CONTACT_PHONE", ""),
    )


def get_shipping_provider(provider_name: Optional[str] = None) -> ShippingProvider:
    """
    Factory method to get the active shipping provider.
    
    Priority:
    1. If provider_name is explicitly specified, use that
    2. Otherwise, use SHIPPING_PROVIDER env var
    3. Fallback to 'manual' if nothing is configured
    """
    name = (provider_name or os.getenv("SHIPPING_PROVIDER", "manual")).lower().strip()

    providers: Dict[str, type] = {
        "borzo": BorzoProvider,
        "porter": PorterProvider,
        "manual": ManualProvider,
    }

    provider_cls = providers.get(name, ManualProvider)
    return provider_cls()


def get_available_providers() -> List[Dict[str, Any]]:
    """Get list of all available shipping providers and their configuration status."""
    all_providers = [
        {
            "id": "borzo",
            "name": "Borzo",
            "description": "On-demand intra-city courier delivery",
            "configured": bool(os.getenv("BORZO_API_TOKEN")),
        },
        {
            "id": "porter",
            "name": "Porter",
            "description": "Enterprise logistics and delivery",
            "configured": bool(os.getenv("PORTER_API_KEY")),
        },
        {
            "id": "manual",
            "name": "Self / Manual Delivery",
            "description": "Handle delivery internally, track through dashboard",
            "configured": True,
        },
    ]
    return all_providers
