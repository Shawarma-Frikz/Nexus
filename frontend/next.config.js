/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/attendance-api/:path*',
        destination: 'http://127.0.0.1:8000/attendance-api/:path*',
      },
    ];
  },
};

module.exports = nextConfig;
