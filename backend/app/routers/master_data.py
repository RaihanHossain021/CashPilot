import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_business_id
from app.db import get_db
from app.models import Customer, Product, Supplier
from app.schemas import (
    CustomerCreate,
    CustomerOut,
    ProductCreate,
    ProductOut,
    SupplierCreate,
    SupplierOut,
)

router = APIRouter(tags=["master-data"])


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> list[Customer]:
    return (
        db.query(Customer)
        .filter(Customer.business_id == business_id)
        .order_by(Customer.name.asc())
        .all()
    )


@router.post("/customers", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> Customer:
    customer = Customer(
        business_id=business_id,
        name=payload.name.strip(),
        phone=payload.phone.strip() if payload.phone else None,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> list[Supplier]:
    return (
        db.query(Supplier)
        .filter(Supplier.business_id == business_id)
        .order_by(Supplier.name.asc())
        .all()
    )


@router.post("/suppliers", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
def create_supplier(
    payload: SupplierCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> Supplier:
    supplier = Supplier(
        business_id=business_id,
        name=payload.name.strip(),
        phone=payload.phone.strip() if payload.phone else None,
    )
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


@router.get("/products", response_model=list[ProductOut])
def list_products(
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> list[Product]:
    return (
        db.query(Product)
        .filter(Product.business_id == business_id)
        .order_by(Product.name.asc())
        .all()
    )


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> Product:
    sku = payload.sku.strip()
    product = Product(
        business_id=business_id,
        name=payload.name.strip(),
        sku=sku,
        kind=payload.kind,
        unit=payload.unit.strip(),
        track_inventory=payload.track_inventory,
        reorder_level=payload.reorder_level,
        sale_price=payload.sale_price,
        avg_cost=payload.avg_cost,
        expiry_date=payload.expiry_date,
    )
    db.add(product)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A product with SKU '{sku}' already exists in this business",
        ) from exc
    db.refresh(product)
    return product
