from app.services.endpoint_service import normalize_path

def test_normalize_path():
    # Test UUID replacement
    assert normalize_path("/api/users/123e4567-e89b-12d3-a456-426614174000") == "/api/users/{uuid}"

    # Test Integer ID replacement
    assert normalize_path("/api/products/456") == "/api/products/{id}"
    
    # Test no change on standard paths
    assert normalize_path("/api/health") == "/api/health"
