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
        return Promise.reject(new Error(data.message || '请求失败'))
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
    return Promise.reject(new Error(msg))
  }
)

export default api
