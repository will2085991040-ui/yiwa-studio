/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 产品化：输出纯静态站点（out/），由桌面态 YIWA.exe 同源托管，前端相对 /api 直达后端
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;