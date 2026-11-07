import { updateDevice, type DeviceResponse } from "@/client";
import { unwrap } from "@/lib/api";
import { toastError } from "@/lib/toast";

export async function saveDeviceTags(
  deviceId: number,
  tags: string[],
  onChanged: (device: DeviceResponse) => void,
  errorMessage = "Failed to update tags",
): Promise<void> {
  try {
    const updated = await unwrap(updateDevice({ path: { device_id: deviceId }, body: { tags } }));
    onChanged(updated);
  } catch (e) {
    toastError(e, errorMessage);
  }
}
