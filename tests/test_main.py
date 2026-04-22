import pytest

@pytest.mark.asyncio
async def test_health_check(async_client):
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

@pytest.mark.asyncio
async def test_demo_products(async_client):
    response = await async_client.get("/api/v1/products?category=software&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert data["category"] == "software"
    assert "items" in data
