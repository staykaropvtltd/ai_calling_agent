import requests
from app.config.settings import BLAND_API_KEY
from app.schemas.caller import CallerRequest


def trigger_bland_call(request: CallerRequest):

    url = "https://api.bland.ai/v1/calls"

    headers = {
        "Authorization": BLAND_API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "phone_number": request.phone_number,
        "task": f"""
You are a polite hotel receptionist from Staykaro.

Call the customer named {request.customer_name}.

Tell them they have a reservation at {request.hotel_name}.

Their check-in date is {request.check_in_date}.

Their check-out date is {request.check_out_date}.

Introduce yourself politely.

Ask whether they are still planning to stay.

If they confirm, thank them and say their booking is confirmed.

If they ask questions about dates, answer correctly using the booking information.

If they want to cancel or change the booking, politely tell them a hotel executive will contact them shortly.

Keep the conversation friendly and professional.
"""
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload
    )

    return response.json()