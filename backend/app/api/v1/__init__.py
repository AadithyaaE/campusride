"""Version 1 REST API. Routers are thin: parse → call a service → map to a DTO.

Now: health, auth, stops, routes, buses (fleet + live state), driver telemetry,
sim (dev/demo controls), students (read-only college-assigned bus), boarding
(QR scan, trip boarding). Later
phases add trips, eta, decision, recovery, boarding, driver,
alerts, admin (incl. assignment management), sim and the /ws WebSocket —
each as its own module registered here.
"""

from fastapi import APIRouter

from app.api.v1 import auth, boarding, buses, driver, health, routes, sim, stops, students

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(stops.router)
api_router.include_router(routes.router)
api_router.include_router(buses.router)
api_router.include_router(driver.router)
api_router.include_router(sim.router)
api_router.include_router(students.router)
api_router.include_router(boarding.router)
