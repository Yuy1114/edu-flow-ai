import axios from "axios";
import { toast } from "sonner";

interface ApiResponse<T> {
  code: number;
  message?: string;
  data: T;
}

const instance = axios.create({
  baseURL: "",
  timeout: 300000,
});

// 请求拦截：自动带 token
instance.interceptors.request.use((config) => {
  const token = localStorage.getItem("edu-flow-token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 响应拦截：统一解包
instance.interceptors.response.use(
  (response) => {
    const res = response.data as ApiResponse<unknown>;
    if (res.code !== 0) {
      const msg = res.message || "请求失败";
      if (!(response.config as any).suppressErrorToast) toast.error(msg);
      return Promise.reject(new Error(msg));
    }
    return res.data as any;
  },
  (error) => {
    const msg = error.response?.data?.message || error.message || "网络错误";
    if (!error.config?.suppressErrorToast) toast.error(msg);
    return Promise.reject(error);
  }
);

// 导出类型方法
const request = {
  get<T = any>(url: string, config?: any): Promise<T> {
    return instance.get(url, config) as Promise<T>;
  },
  post<T = any>(url: string, data?: any, config?: any): Promise<T> {
    return instance.post(url, data, config) as Promise<T>;
  },
  put<T = any>(url: string, data?: any, config?: any): Promise<T> {
    return instance.put(url, data, config) as Promise<T>;
  },
  delete<T = any>(url: string, config?: any): Promise<T> {
    return instance.delete(url, config) as Promise<T>;
  },
};

export default request;
