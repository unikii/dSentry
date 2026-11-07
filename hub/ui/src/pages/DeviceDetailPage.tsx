import { useEffect, useState } from "react";
import { useLocation, useNavigate, useOutletContext, useParams } from "react-router-dom";
import { getDevice, type DeviceResponse } from "@/client";
import { Skeleton } from "@/components/ui/skeleton";
import { dedupeRequest, unwrap } from "@/lib/api";
import { toastError } from "@/lib/toast";
import { DeviceDetailView } from "@/components/device/DeviceDetailView";
import { useEnvs } from "@/context/use-envs";
import { useLanguage } from "@/context/use-lang";
import { tStatic } from "@/i18n";

type DetailLocationState = { from?: string; nodeName?: string; nodeId?: number };
type DevicesOutletContext = { onChanged: (device: DeviceResponse) => void; nodeName?: string; nodeId?: number };

const deviceRequests = new Map<number, Promise<DeviceResponse>>();

function getDeviceOnce(id: number): Promise<DeviceResponse> {
  return dedupeRequest(deviceRequests, id, () => unwrap(getDevice({ path: { device_id: id } })));
}

export function DeviceDetailPage() {
  const { t } = useLanguage();
  const { deviceId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { onChanged: onGridChanged, nodeName: nodeNameFromGrid } = useOutletContext<DevicesOutletContext>();
  const detailState = location.state as DetailLocationState | null;
  const nodeName = detailState?.nodeName ?? nodeNameFromGrid;
  const { envs } = useEnvs();
  const pushInterval = envs?.global_push_interval;
  const [device, setDevice] = useState<DeviceResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const id = Number(deviceId);
    setDevice(null);
    setLoading(true);
    if (!Number.isInteger(id) || id < 1) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    getDeviceOnce(id)
      .then((nextDevice) => {
        if (cancelled) return;
        setDevice(nextDevice);
      })
      .catch((e) => {
        if (!cancelled) toastError(e, tStatic("detail.failedLoad"));
      })
      .finally(() => !cancelled && setLoading(false));

    return () => {
      cancelled = true;
    };
  }, [deviceId]);

  const from = detailState?.from;
  const goBack = () => (from ? navigate(-1) : navigate("/devices", { replace: true }));

  if (loading) {
    return (
      <div className="flex flex-col gap-5 py-6">
        <Skeleton className="h-8 w-28" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-10 w-80" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (!device) {
    return (
      <div className="flex flex-col items-start gap-4 py-12">
        <p className="text-muted-foreground text-sm">{t("detail.notFound")}</p>
        <button type="button" className="text-primary text-sm font-medium hover:underline" onClick={goBack}>
          {t("detail.backToDevices")}
        </button>
      </div>
    );
  }

  return (
    <DeviceDetailView
      device={device}
      nodeName={nodeName}
      pushInterval={pushInterval}
      onBack={goBack}
      onChanged={(updated) => {
        setDevice(updated);
        onGridChanged(updated);
      }}
    />
  );
}
