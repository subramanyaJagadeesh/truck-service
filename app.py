from fastapi import FastAPI, HTTPException, Path, Body, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, Integer, String, JSON, Enum
from enum import Enum as PyEnum
from typing import Optional, List

# Initialize FastAPI app
app = FastAPI()

# Database setup
DATABASE_URL = "postgresql+asyncpg://username:password@localhost/yourdatabase"
engine = create_async_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# Status Enum
class RequestStatus(str, PyEnum):
    OPENED = "opened"
    ASSIGNED = "assigned"
    SERVED = "served"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"

# Database model
class ServiceRequest(Base):
    __tablename__ = "service_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    drop_off_location = Column(String, nullable=False)
    shipment_metadata = Column(JSON, nullable=False)
    truck_id = Column(Integer, nullable=True)
    status = Column(Enum(RequestStatus), default=RequestStatus.OPENED)

# Pydantic models
class ShipmentMetadata(BaseModel):
    weight: str
    type: str

class ServiceRequestCreate(BaseModel):
    drop_off_location: str
    shipment_metadata: ShipmentMetadata

class ServiceRequestAssign(BaseModel):
    truck_id: int

class ServiceRequestUpdate(BaseModel):
    status: RequestStatus
    details: Optional[dict] = None

# Initialize database
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# Dependency
async def get_db():
    async with SessionLocal() as session:
        yield session

# Create Service Request
@app.post("/api/service-request", status_code=201)
async def create_service_request(request_data: ServiceRequestCreate, db: AsyncSession = Depends(get_db)):
    new_request = ServiceRequest(
        drop_off_location=request_data.drop_off_location,
        shipment_metadata=request_data.shipment_metadata.dict(),
        status=RequestStatus.OPENED
    )
    db.add(new_request)
    await db.commit()
    await db.refresh(new_request)
    return {"request_id": new_request.id, "status": new_request.status}

# Assign Service Request to Truck
@app.put("/api/service-request/{request_id}/assign", status_code=200)
async def assign_service_request(request_id: int, assign_data: ServiceRequestAssign, db: AsyncSession = Depends(get_db)):
    request = await db.get(ServiceRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.status != RequestStatus.OPENED:
        raise HTTPException(status_code=400, detail="Request is not in 'opened' status")
    
    request.truck_id = assign_data.truck_id
    request.status = RequestStatus.ASSIGNED
    await db.commit()
    await db.refresh(request)
    return {"request_id": request.id, "truck_id": request.truck_id, "status": request.status}

# Update Service Request Status
@app.put("/api/service-request/{request_id}/status", status_code=200)
async def update_request_status(request_id: int, update_data: ServiceRequestUpdate, db: AsyncSession = Depends(get_db)):
    request = await db.get(ServiceRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    if update_data.status not in RequestStatus.__members__.values():
        raise HTTPException(status_code=400, detail="Invalid status transition")

    request.status = update_data.status
    await db.commit()
    await db.refresh(request)
    return {"success": True, "message": "Request updated successfully"}

# Delete Service Request
@app.delete("/api/service-request/{request_id}", status_code=200)
async def delete_service_request(request_id: int, db: AsyncSession = Depends(get_db)):
    request = await db.get(ServiceRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    await db.delete(request)
    await db.commit()
    return {"success": True, "message": "Request deleted successfully"}

# Get All Service Requests
@app.get("/api/service-requests", status_code=200)
async def get_all_requests(db: AsyncSession = Depends(get_db)):
    requests = await db.execute("SELECT * FROM service_requests")
    results = requests.fetchall()
    if not results:
        raise HTTPException(status_code=404, detail="No requests found")

    return [
        {
            "request_id": req.id,
            "status": req.status,
            "drop_off_location": req.drop_off_location,
            "shipment_metadata": req.shipment_metadata,
            "truck_id": req.truck_id
        } for req in results
    ]

# Run database initialization on startup
@app.on_event("startup")
async def startup():
    await init_db()
