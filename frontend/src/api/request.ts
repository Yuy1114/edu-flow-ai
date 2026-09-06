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
    // 文件下载不走统一信封：调用方需要原始 blob 和响应头里的文件名。
    if (response.config.responseType === "blob") return response as any;
    const res = response.data as ApiResponse<unknown>;
    if (res.code !== 0) {
      const msg = res.message || "请求失败";
      if (!(response.config as any).suppressErrorToast) toast.error(msg);
      return Promise.reject(new Error(msg));
    }
    return res.data as any;
  },
  async (error) => {
    // blob 请求失败时响应体也是 blob，要先读出来才能拿到后端的错误说明。
    let msg = error.response?.data?.message || error.message || "网络错误";
    if (error.response?.data instanceof Blob) {
      try {
        const parsed = JSON.parse(await error.response.data.text());
        if (parsed?.message) msg = parsed.message;
      } catch {
        // 不是 JSON 就保留原始错误信息
      }
    }
    if (!error.config?.suppressErrorToast) toast.error(msg);
    return Promise.reject(new Error(msg));
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
  /** 下载文件：返回 blob 与后端给出的文件名。 */
  async download(url: string, config?: any): Promise<{ blob: Blob; fileName: string }> {
    const response: any = await instance.get(url, { ...config, responseType: "blob" });
    return {
      blob: response.data as Blob,
      fileName: fileNameFrom(response.headers?.["content-disposition"]),
    };
  },
};

/** 解析 Content-Disposition：优先 RFC 5987 的 filename*，退回普通 filename。 */
function fileNameFrom(disposition: string | undefined): string {
  if (!disposition) return "";
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch {
      return encoded[1];
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain ? plain[1] : "";
}

export default request;
