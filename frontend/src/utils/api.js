import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  withCredentials: true,
})

api.interceptors.response.use(
  (response) => {
    const data = response.data
    if (data && typeof data === 'object' && 'success' in data) {
      if (!data.success) {
        return Promise.reject({
          message: data.message || '请求失败',
          code: data.code,
          raw: data,
          status: response.status,
        })
      }
      return data
    }
    return response
  },
  (error) => {
    if (error.code === 'ERR_CANCELED' || error.code === 'ECONNABORTED') {
      return Promise.reject(new Error('请求已取消'))
    }
    if (!error.response) {
      return Promise.reject(new Error(error.message || '网络连接失败'))
    }
    if (error.response?.status === 401) {
      localStorage.removeItem('user')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
      return Promise.reject(new Error('请先登录'))
    }
    const msg = error.response?.data?.message || error.message || '网络错误'
    const code = error.response?.data?.code
    return Promise.reject({
      message: msg,
      code: code,
      raw: error.response?.data,
      status: error.response?.status,
    })
  }
)

export const authApi = {
  login: (data) => api.post('/auth/login', data),
  logout: () => api.post('/auth/logout'),
  me: () => api.get('/auth/me'),
}

export const userApi = {
  list: () => api.get('/users/list'),
}

export const handoverApi = {
  list: (params) => api.get('/handover-sheets', { params }),
  create: (data) => api.post('/handover-sheets', data),
  getDetail: (id, params) => api.get(`/handover-sheets/${id}`, { params }),
  sign: (id, data) => api.post(`/handover-sheets/${id}/sign`, data),
  void: (id, data) => api.post(`/handover-sheets/${id}/void`, data),
  checkConflicts: (id) => api.post(`/handover-sheets/${id}/check-conflicts`),
  availableLabels: (params) => api.get('/handover-sheets/available-labels', { params }),
  assign: (id, data) => api.post(`/handover-sheets/${id}/assign`, data),
  listAuthorizations: (id) => api.get(`/handover-sheets/${id}/authorizations`),
  authorize: (id, data) => api.post(`/handover-sheets/${id}/authorize`, data),
  revokeAuth: (authId, data) => api.post(`/handover-authorizations/${authId}/revoke`, data),
  revokeSign: (id, data) => api.post(`/handover-sheets/${id}/revoke-sign`, data),
  reopen: (id, data) => api.post(`/handover-sheets/${id}/reopen`, data),
}

export const authStationApi = {
  summary: () => api.get('/handover-auth-station/summary'),
  validateToken: (data) => api.post('/handover-authorizations/validate', data),
  listReceipts: (params) => api.get('/handover-receipts', { params }),
  getReceipt: (id) => api.get(`/handover-receipts/${id}`),
  listAuditLogs: (params) => api.get('/handover-audit-logs', { params }),
  auditTimeline: (params) => api.get('/handover-audit-logs/timeline', { params }),
}

export const exportApi = {
  handoverSheets: (params) => {
    const qs = new URLSearchParams(params || {}).toString()
    window.open(`/api/export/handover-sheets${qs ? '?' + qs : ''}`, '_blank')
  },
  handoverSheet: (id) => {
    window.open(`/api/export/handover-sheet/${id}`, '_blank')
  },
  handoverLogs: (params) => {
    const qs = new URLSearchParams(params || {}).toString()
    window.open(`/api/export/handover-logs${qs ? '?' + qs : ''}`, '_blank')
  },
  auditLogs: () => {
    window.open('/api/export/handover-audit-logs', '_blank')
  },
  receipts: () => {
    window.open('/api/export/handover-receipts', '_blank')
  },
}

export const drillApi = {
  listScenarios: () => api.get('/drill/scenarios'),
  listDemoData: () => api.get('/drill/demo-data'),
  getDemoData: (key) => api.get(`/drill/demo-data/${key}`),
  importDemoData: (data) => api.post('/drill/demo-data/import', data),
  resetDemoData: (key, data) => api.post(`/drill/demo-data/${key}/reset`, data || {}),
}

export default api
