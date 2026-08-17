"""
Tests for restocking recommendation and order endpoints.
"""
from datetime import datetime, timedelta

class TestRestockRecommendations:
    """Test suite for GET /api/restock/recommendations."""

    def test_get_recommendations_structure(self, client):
        """Test the response shape of a recommendation request."""
        response = client.get("/api/restock/recommendations?budget=25000")
        assert response.status_code == 200

        data = response.json()
        for key in ["budget", "total_cost", "remaining_budget", "items", "skipped_forecasts"]:
            assert key in data
        assert data["budget"] == 25000
        assert isinstance(data["items"], list)
        assert len(data["items"]) > 0

        first = data["items"][0]
        for key in [
            "sku", "name", "category", "warehouse", "quantity_on_hand", "current_demand",
            "forecasted_demand", "trend", "shortfall", "unit_cost", "recommended_quantity",
            "line_total", "lead_time_days",
        ]:
            assert key in first

    def test_recommendations_stay_within_budget(self, client):
        """Test that the planned spend never exceeds the budget."""
        for budget in [0, 500, 5000, 25000, 200000]:
            data = client.get(f"/api/restock/recommendations?budget={budget}").json()
            assert data["total_cost"] <= budget + 0.01
            assert abs(data["remaining_budget"] - (budget - data["total_cost"])) < 0.01
            line_sum = sum(item["line_total"] for item in data["items"])
            assert abs(line_sum - data["total_cost"]) < 0.01

    def test_recommendations_sorted_by_shortfall(self, client):
        """Test that items with the largest shortfall come first."""
        data = client.get("/api/restock/recommendations?budget=25000").json()
        shortfalls = [item["shortfall"] for item in data["items"]]
        assert shortfalls == sorted(shortfalls, reverse=True)

    def test_recommended_quantity_never_exceeds_shortfall(self, client):
        """Test that the recommender does not buy more than the forecast gap."""
        data = client.get("/api/restock/recommendations?budget=200000").json()
        for item in data["items"]:
            assert 0 <= item["recommended_quantity"] <= item["shortfall"]
            assert abs(item["line_total"] - item["recommended_quantity"] * item["unit_cost"]) < 0.01

    def test_zero_budget_recommends_nothing(self, client):
        """Test that a zero budget yields no quantities but still lists candidates."""
        data = client.get("/api/restock/recommendations?budget=0").json()
        assert data["total_cost"] == 0
        assert len(data["items"]) > 0
        for item in data["items"]:
            assert item["recommended_quantity"] == 0

    def test_negative_budget_rejected(self, client):
        """Test that a negative budget is a bad request."""
        response = client.get("/api/restock/recommendations?budget=-1")
        assert response.status_code == 400

    def test_recommended_skus_exist_in_inventory(self, client):
        """Test that every candidate is a real inventory item with a matching lead time."""
        inventory = {item["sku"]: item for item in client.get("/api/inventory").json()}
        data = client.get("/api/restock/recommendations?budget=25000").json()
        for item in data["items"]:
            assert item["sku"] in inventory
            assert item["unit_cost"] == inventory[item["sku"]]["unit_cost"]
            assert item["quantity_on_hand"] == inventory[item["sku"]]["quantity_on_hand"]
            assert item["lead_time_days"] > 0

    def test_forecasts_without_inventory_are_skipped(self, client):
        """Test that forecasts for unknown SKUs are counted, not recommended."""
        inventory_skus = {item["sku"] for item in client.get("/api/inventory").json()}
        forecasts = client.get("/api/demand").json()
        orphan_count = sum(1 for f in forecasts if f["item_sku"] not in inventory_skus)
        assert orphan_count >= 8

        data = client.get("/api/restock/recommendations?budget=25000").json()
        assert data["skipped_forecasts"] == orphan_count

    def test_recommendations_by_warehouse(self, client):
        """Test that the warehouse filter restricts candidates."""
        data = client.get("/api/restock/recommendations?budget=25000&warehouse=Tokyo").json()
        assert len(data["items"]) > 0
        for item in data["items"]:
            assert item["warehouse"] == "Tokyo"

    def test_recommendations_by_category(self, client):
        """Test that the category filter is case-insensitive."""
        data = client.get("/api/restock/recommendations?budget=25000&category=actuators").json()
        assert len(data["items"]) > 0
        for item in data["items"]:
            assert item["category"].lower() == "actuators"


class TestRestockOrders:
    """Test suite for POST/GET /api/restock/orders."""

    def _payload(self, client, budget=100000):
        """Build a valid order from the first two recommended items."""
        rec = client.get(f"/api/restock/recommendations?budget={budget}").json()
        chosen = [i for i in rec["items"] if i["recommended_quantity"] > 0][:2]
        assert len(chosen) == 2
        return {
            "budget": budget,
            "items": [{"sku": i["sku"], "quantity": i["recommended_quantity"]} for i in chosen],
        }, chosen

    def test_create_restock_order(self, client):
        """Test that a valid order is created with correct totals and lead times."""
        payload, chosen = self._payload(client)
        response = client.post("/api/restock/orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-")
        assert len(order["items"]) == 2

        expected_total = sum(i["recommended_quantity"] * i["unit_cost"] for i in chosen)
        assert abs(order["total_cost"] - expected_total) < 0.01
        assert order["lead_time_days"] == max(i["lead_time_days"] for i in chosen)

        for line, source in zip(order["items"], chosen):
            assert line["sku"] == source["sku"]
            assert line["lead_time_days"] == source["lead_time_days"]
            assert "T" in line["expected_delivery"]

    def test_expected_delivery_matches_lead_time(self, client):
        """Test that expected delivery is order date plus the slowest line's lead time."""
        payload, _ = self._payload(client)
        order = client.post("/api/restock/orders", json=payload).json()
        order_date = datetime.fromisoformat(order["order_date"])
        expected = order_date + timedelta(days=order["lead_time_days"])
        assert datetime.fromisoformat(order["expected_delivery"]) == expected

    def test_list_restock_orders_newest_first(self, client):
        """Test that submitted orders are listed with the newest first."""
        payload, _ = self._payload(client)
        first = client.post("/api/restock/orders", json=payload).json()
        second = client.post("/api/restock/orders", json=payload).json()

        response = client.get("/api/restock/orders")
        assert response.status_code == 200
        orders = response.json()
        ids = [o["id"] for o in orders]
        assert ids.index(second["id"]) < ids.index(first["id"])

    def test_order_over_budget_rejected(self, client):
        """Test that an order costing more than its budget is rejected."""
        payload, _ = self._payload(client)
        payload["budget"] = 1
        response = client.post("/api/restock/orders", json=payload)
        assert response.status_code == 400
        assert "exceeds budget" in response.json()["detail"]

    def test_order_unknown_sku_rejected(self, client):
        """Test that an unknown SKU is rejected."""
        response = client.post(
            "/api/restock/orders",
            json={"budget": 1000, "items": [{"sku": "NOPE-000", "quantity": 1}]},
        )
        assert response.status_code == 400
        assert "NOPE-000" in response.json()["detail"]

    def test_order_zero_quantity_rejected(self, client):
        """Test that a zero quantity fails validation."""
        response = client.post(
            "/api/restock/orders",
            json={"budget": 1000, "items": [{"sku": "PSU-501", "quantity": 0}]},
        )
        assert response.status_code == 422

    def test_order_without_items_rejected(self, client):
        """Test that an empty item list fails validation."""
        response = client.post("/api/restock/orders", json={"budget": 1000, "items": []})
        assert response.status_code == 422
