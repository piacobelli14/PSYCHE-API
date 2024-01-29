from get_sessions import get_sessions

# Simulate a GET request payload
event = {
    'httpMethod': 'GET',
}

# Call the get_sessions function with the simulated event
response = get_sessions(event)
print("Response:", response)
