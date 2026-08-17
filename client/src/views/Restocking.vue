<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div class="card budget-card">
      <div class="card-header">
        <h3 class="card-title">{{ t('restocking.budget') }}</h3>
      </div>
      <div class="budget-value">{{ formatCurrency(budget, currentCurrency) }}</div>
      <div class="budget-controls">
        <label for="budget-slider" class="visually-hidden">{{ t('restocking.budget') }}</label>
        <input
          id="budget-slider"
          type="range"
          min="0"
          max="200000"
          step="1000"
          v-model.number="budget"
          class="budget-slider"
        />
        <label for="budget-input" class="visually-hidden">{{ t('restocking.budget') }}</label>
        <input
          id="budget-input"
          type="number"
          min="0"
          step="1000"
          :value="budget"
          @input="onBudgetInput"
          class="budget-input"
        />
      </div>
      <p class="budget-hint">{{ t('restocking.budgetHint') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.budget') }}</div>
          <div class="stat-value">{{ formatCurrency(budget, currentCurrency) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.plannedSpend') }}</div>
          <div class="stat-value">{{ formatCurrency(selectedTotal, currentCurrency) }}</div>
        </div>
        <div class="stat-card" :class="remainingBudget < 0 ? 'danger' : 'success'">
          <div class="stat-label">{{ t('restocking.remaining') }}</div>
          <div class="stat-value">{{ formatCurrency(remainingBudget, currentCurrency) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.itemsToOrder') }}</div>
          <div class="stat-value">{{ selectedItems.length }}</div>
        </div>
      </div>

      <div v-if="orderConfirmation" class="card confirmation-card">
        <p class="confirmation-title">
          {{ t('restocking.orderPlaced', { orderNumber: orderConfirmation.order_number }) }}
        </p>
        <p class="confirmation-detail">
          {{ t('restocking.orderPlacedDetail', {
            count: orderConfirmation.items.length,
            total: formatCurrency(orderConfirmation.total_cost, currentCurrency),
            date: formatDate(orderConfirmation.expected_delivery),
            days: orderConfirmation.lead_time_days
          }) }}
        </p>
        <div class="confirmation-actions">
          <router-link to="/orders" class="btn btn-secondary">{{ t('restocking.viewOrders') }}</router-link>
          <button class="btn btn-secondary" @click="orderConfirmation = null">{{ t('restocking.placeAnother') }}</button>
        </div>
      </div>

      <div v-if="submitError" class="error">
        {{ t('restocking.orderFailed') }}: {{ submitError }}
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <h3 class="card-title">{{ t('restocking.recommendations') }} ({{ recommendations.length }})</h3>
            <p class="card-subtitle">{{ t('restocking.recommendationsHint') }}</p>
          </div>
          <button
            class="btn btn-primary"
            :disabled="!canPlaceOrder"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>

        <p v-if="skippedForecasts > 0" class="skipped-note">
          {{ t('restocking.skippedNote', { count: skippedForecasts }) }}
        </p>

        <div v-if="recommendations.length === 0" class="empty-state">
          {{ t('restocking.noCandidates') }}
        </div>
        <div v-else class="table-container" :class="{ refreshing }">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.select') }}</th>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.category') }}</th>
                <th>{{ t('restocking.table.warehouse') }}</th>
                <th>{{ t('restocking.table.onHand') }}</th>
                <th>{{ t('restocking.table.forecast') }}</th>
                <th>{{ t('restocking.table.shortfall') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.quantity') }}</th>
                <th>{{ t('restocking.table.lineTotal') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in recommendations"
                :key="item.sku"
                :class="{ 'row-disabled': item.recommended_quantity === 0 }"
              >
                <td>
                  <input
                    type="checkbox"
                    :checked="!!selected[item.sku]"
                    :disabled="item.recommended_quantity === 0"
                    @change="toggleSelected(item)"
                  />
                </td>
                <td><strong>{{ item.sku }}</strong></td>
                <td>{{ translateProductName(item.name) }}</td>
                <td>{{ item.category }}</td>
                <td>{{ translateWarehouse(item.warehouse) }}</td>
                <td>{{ item.quantity_on_hand.toLocaleString() }}</td>
                <td>
                  {{ item.forecasted_demand.toLocaleString() }}
                  <span :class="['badge', item.trend]">{{ t(`trends.${item.trend}`) }}</span>
                </td>
                <td>{{ item.shortfall.toLocaleString() }}</td>
                <td>{{ formatCurrency(item.unit_cost, currentCurrency) }}</td>
                <td>{{ item.recommended_quantity.toLocaleString() }}</td>
                <td>{{ formatCurrency(item.line_total, currentCurrency) }}</td>
                <td>{{ t('orders.leadTimeDays', { days: item.lead_time_days }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useFilters } from '../composables/useFilters'
import { useI18n } from '../composables/useI18n'
import { formatCurrency } from '../utils/currency'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentLocale, currentCurrency, translateProductName, translateWarehouse } = useI18n()

    // Inventory has no time dimension, so month/period filter is intentionally excluded here
    const { selectedLocation, selectedCategory } = useFilters()

    const loading = ref(true)
    // Only the first load blocks the whole view; later refetches (slider drags, filter
    // changes) keep the table mounted and just dim it via `refreshing` to avoid flicker
    const initialLoad = ref(true)
    const refreshing = ref(false)
    const error = ref(null)
    const submitting = ref(false)
    const submitError = ref(null)
    const orderConfirmation = ref(null)

    const budget = ref(25000)
    const recommendations = ref([])
    const skippedForecasts = ref(0)
    const selected = ref({})

    let debounceTimer = null

    const initSelection = () => {
      const next = {}
      for (const item of recommendations.value) {
        if (item.recommended_quantity > 0) {
          next[item.sku] = true
        }
      }
      selected.value = next
    }

    const loadRecommendations = async () => {
      try {
        if (initialLoad.value) {
          loading.value = true
        } else {
          refreshing.value = true
        }
        error.value = null
        // Guard against a non-numeric/negative budget slipping through (e.g. mid-edit
        // of the number input) so the API never receives budget= or a negative value
        if (!Number.isFinite(budget.value) || budget.value < 0) {
          budget.value = 0
        }
        const filters = { warehouse: selectedLocation.value, category: selectedCategory.value }
        const data = await api.getRestockRecommendations(budget.value, filters)
        recommendations.value = data.items
        skippedForecasts.value = data.skipped_forecasts
        initSelection()
      } catch (err) {
        error.value = 'Failed to load restock recommendations: ' + err.message
      } finally {
        loading.value = false
        refreshing.value = false
        initialLoad.value = false
      }
    }

    const onBudgetInput = (event) => {
      const parsed = Number(event.target.value)
      // Coerce empty/NaN/negative typed values to 0 so `budget` stays numeric
      budget.value = Number.isFinite(parsed) && parsed >= 0 ? parsed : 0
    }

    const toggleSelected = (item) => {
      const next = { ...selected.value }
      if (next[item.sku]) {
        delete next[item.sku]
      } else {
        next[item.sku] = true
      }
      selected.value = next
    }

    const selectedItems = computed(() => recommendations.value.filter(item => selected.value[item.sku]))
    const selectedTotal = computed(() => selectedItems.value.reduce((sum, item) => sum + item.line_total, 0))
    const remainingBudget = computed(() => budget.value - selectedTotal.value)

    const canPlaceOrder = computed(() => {
      return !submitting.value && selectedItems.value.length > 0 && selectedTotal.value <= budget.value
    })

    const placeOrder = async () => {
      submitting.value = true
      submitError.value = null
      try {
        const payload = {
          budget: budget.value,
          items: selectedItems.value.map(item => ({ sku: item.sku, quantity: item.recommended_quantity }))
        }
        const order = await api.createRestockOrder(payload)
        orderConfirmation.value = order
        await loadRecommendations()
      } catch (err) {
        submitError.value = err.response?.data?.detail || err.message
      } finally {
        submitting.value = false
      }
    }

    // Debounce budget changes so slider dragging doesn't fire an API call per tick
    watch(budget, () => {
      clearTimeout(debounceTimer)
      debounceTimer = setTimeout(loadRecommendations, 300)
    })

    // Warehouse/category changes should refetch immediately (no debounce needed)
    watch([selectedLocation, selectedCategory], () => {
      loadRecommendations()
    })

    const formatDate = (dateString) => {
      const locale = currentLocale.value === 'ja' ? 'ja-JP' : 'en-US'
      const date = new Date(dateString)
      if (isNaN(date.getTime())) return dateString
      return date.toLocaleDateString(locale, { year: 'numeric', month: 'short', day: 'numeric' })
    }

    onMounted(loadRecommendations)

    return {
      t,
      currentCurrency,
      loading,
      refreshing,
      error,
      submitting,
      submitError,
      orderConfirmation,
      budget,
      recommendations,
      skippedForecasts,
      selected,
      selectedItems,
      selectedTotal,
      remainingBudget,
      canPlaceOrder,
      toggleSelected,
      onBudgetInput,
      placeOrder,
      formatCurrency,
      formatDate,
      translateProductName,
      translateWarehouse
    }
  }
}
</script>

<style scoped>
.budget-card {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.budget-value {
  font-size: 2.5rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
}

.budget-controls {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.budget-slider {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: #e2e8f0;
  appearance: none;
  outline: none;
}

.budget-slider::-webkit-slider-thumb {
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
}

.budget-slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border: none;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
}

.budget-input {
  width: 140px;
  padding: 0.5rem 0.625rem;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 0.938rem;
  color: #0f172a;
}

.budget-hint {
  color: #64748b;
  font-size: 0.813rem;
  margin: 0;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}

.card-subtitle {
  color: #64748b;
  font-size: 0.813rem;
  margin-top: 0.25rem;
}

.skipped-note {
  color: #64748b;
  font-size: 0.813rem;
  margin: 0 0 0.75rem;
}

.empty-state {
  color: #64748b;
  padding: 1.5rem 0;
  text-align: center;
}

.table-container.refreshing {
  opacity: 0.55;
  transition: opacity 0.15s ease;
}

.row-disabled {
  color: #94a3b8;
  background: #f8fafc;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.625rem 1.25rem;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  border: none;
  text-decoration: none;
}

.btn-primary {
  background: #3b82f6;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #2563eb;
}

.btn-primary:disabled {
  background: #cbd5e1;
  color: #64748b;
  cursor: not-allowed;
}

.btn-secondary {
  background: white;
  color: #0f172a;
  border: 1px solid #e2e8f0;
}

.btn-secondary:hover {
  border-color: #cbd5e1;
}

.confirmation-card {
  border-color: #a7f3d0;
  background: #ecfdf5;
}

.confirmation-title {
  font-weight: 700;
  color: #065f46;
  margin: 0 0 0.375rem;
}

.confirmation-detail {
  color: #065f46;
  margin: 0 0 0.75rem;
}

.confirmation-actions {
  display: flex;
  gap: 0.75rem;
}
</style>
