import pytest

@pytest.mark.asyncio
async def test_user_signup_success(async_client):
    payload = {
        "name": "Test User",
        "org": "Test Org",
        "email": "test@example.com",
        "password": "securepassword123"
    }
    response = await async_client.post("/api/auth/signup", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert "api_key" in data
    assert data["email"] == "test@example.com"

@pytest.mark.asyncio
async def test_user_signup_duplicate(async_client):
    payload = {
        "name": "Test User",
        "org": "Test Org",
        "email": "duplicate@example.com",
        "password": "securepassword123"
    }
    await async_client.post("/api/auth/signup", json=payload)

    # Second attempt should fail
    response = await async_client.post("/api/auth/signup", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered."

@pytest.mark.asyncio
async def test_user_signin(async_client):
    payload = {
        "name": "Test User",
        "org": "Test Org",
        "email": "login@example.com",
        "password": "securepassword123"
    }
    await async_client.post("/api/auth/signup", json=payload)
    login_payload = {"email": "login@example.com", "password": "securepassword123"}
    response = await async_client.post("/api/auth/signin", json=login_payload)
    assert response.status_code == 200
    assert "token" in response.json()
