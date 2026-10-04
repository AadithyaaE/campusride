/**
 * Runtime configuration. The backend URL comes from EXPO_PUBLIC_API_BASE_URL.
 * On an Android emulator the host machine is 10.0.2.2; on a phone use the PC's LAN IP.
 */
export const config = {
  apiBaseUrl: process.env.EXPO_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1",
} as const;
