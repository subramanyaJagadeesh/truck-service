from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from enum import Enum
from datetime import datetime
import json
import requests

# Configuration
app = Flask(__name__)
CORS(app)  # Allows all origins

app.config['SQLALCHEMY_DATABASE_URI'] = "postgresql+psycopg2://postgres:GL85#Y3%$X&c5*yf^Wgt@autonomous-truck-simulator.c3s0ceae4890.us-west-1.rds.amazonaws.com:5432/postgres"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

token = '4923f238-9852-4f14-aaf9-66aa6a9282aa'


# Enums
class RequestStatus(Enum):
    OPENED = "Opened"
    ASSIGNED = "Assigned"
    SERVED = "Served"
    COMPLETE = "Complete"
    INCOMPLETE = "Incomplete"


# Models
class ServiceRequest(db.Model):
    __tablename__ = "service_requests"
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    drop_off_location = db.Column(db.String, nullable=False)
    service_type = db.Column(db.String, nullable=False)
    truck_id = db.Column(db.Integer, nullable=True)
    status = db.Column(db.Enum(RequestStatus), default=RequestStatus.OPENED)
    created_time = db.Column(db.DateTime, default=datetime.utcnow)


# Routes

@app.route("/api/service-request", methods=["POST"])
def create_service_request():
    data = request.get_json()
    if not data or "drop_off_location" not in data or "shipment_metadata" not in data:
        abort(400, "Invalid input data")

    new_request = ServiceRequest(
        drop_off_location=data["drop_off_location"],
        service_type=json.dumps(data["shipment_metadata"]),
        status=RequestStatus.OPENED
    )
    db.session.add(new_request)
    db.session.commit()
    
    requests.post(
        'http://cmpe281-2007092816.us-east-2.elb.amazonaws.com/api/alerts/create',
        json={"token": token, "description": f"Service Request: Created new request {new_request.id}"}
    )
    return jsonify({"request_id": new_request.id, "status": new_request.status.value}), 201


@app.route("/api/service-request/<int:request_id>/assign", methods=["PUT"])
def assign_service_request(request_id):
    data = request.get_json()
    if not data or "truck_id" not in data:
        abort(400, "Invalid input data")

    service_request = ServiceRequest.query.get(request_id)
    if not service_request:
        abort(404, "Request not found")
    if service_request.status != RequestStatus.OPENED:
        abort(400, "Request is not in 'opened' status")

    service_request.truck_id = data["truck_id"]
    service_request.status = RequestStatus.ASSIGNED

    res = requests.post(
        'http://cmpe281-2007092816.us-east-2.elb.amazonaws.com/api/schedule-manager/create',
        json={"stops": [service_request.drop_off_location], "token": token}
    ).json()
    
    path = requests.post(
        f"http://cmpe281-2007092816.us-east-2.elb.amazonaws.com/api/path-manager/{res['schedule_id']}",
        json={"token": token}
    ).json()[0]['path'][0]

    db.session.commit()
    requests.post(
        'http://cmpe281-2007092816.us-east-2.elb.amazonaws.com/api/alerts/create',
        json={"token": token, "description": f"Service Request: Assigned truck to request {request_id}"}
    )
    return jsonify({"request_id": request_id, "truck_id": service_request.truck_id, "status": service_request.status.value, "path": path}), 200


@app.route("/api/service-request/<int:vehicle_id>/status", methods=["PUT"])
def update_request_status(vehicle_id):
    data = request.get_json()
    if not data or "status" not in data:
        abort(400, "Invalid input data")

    if data["status"] not in [status.value for status in RequestStatus]:
        abort(400, "Invalid status")

    service_request = ServiceRequest.query.filter_by(truck_id = vehicle_id).all()
    if not service_request:
        abort(404, "Request not found")

    service_request.status = RequestStatus[data["status"]]
    db.session.commit()
    return jsonify({"success": True, "message": "Request updated successfully"}), 200


@app.route("/api/service-request/<int:request_id>", methods=["DELETE"])
def delete_service_request(request_id):
    service_request = ServiceRequest.query.get(request_id)
    if not service_request:
        abort(404, "Request not found")

    db.session.delete(service_request)
    db.session.commit()
    requests.post(
        'http://cmpe281-2007092816.us-east-2.elb.amazonaws.com/api/alerts/create',
        json={"token": token, "description": f"Service Request: Deleted request {request_id}"}
    )
    return jsonify({"success": True, "message": "Request deleted successfully"}), 200


@app.route("/api/service-requests", methods=["GET"])
def get_all_requests():
    service_requests = ServiceRequest.query.order_by(ServiceRequest.id.asc()).all()
    response_data = [
        {
            "id": request.id,
            "status": request.status.value,
            "drop_off_location": request.drop_off_location,
            "shipment_metadata": request.service_type,
            "truck_id": request.truck_id,
        }
        for request in service_requests
    ]
    return jsonify(response_data), 200


@app.route("/api/service-requests/metadata", methods=["GET"])
def get_metadata():
    open_count = ServiceRequest.query.filter_by(status=RequestStatus.OPENED).count()
    assigned_count = ServiceRequest.query.filter_by(status=RequestStatus.ASSIGNED).count()
    completed_count = ServiceRequest.query.filter_by(status=RequestStatus.COMPLETE).count()
    total_count = ServiceRequest.query.count()

    return jsonify({
        "open": open_count,
        "assigned": assigned_count,
        "completed": completed_count,
        "total": total_count
    }), 200


# Initialize database
@app.before_request
def initialize_database():
    db.create_all()


# Run the app
if __name__ == "__main__":
    app.run(debug=True, port=8000)
