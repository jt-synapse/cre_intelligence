"use client";
import { useEffect, useRef, useState } from "react";
import type { Point } from "../lib/map-geometry";

export type LocationFix = { point: Point; accuracy: number };

export function useFieldLocation(
  onFix: (fix: LocationFix, first: boolean) => void,
) {
  const [fix, setFix] = useState<LocationFix | null>(null);
  const [following, setFollowing] = useState(false);
  const [message, setMessage] = useState("");
  const watch = useRef<number | null>(null);
  const epoch = useRef(0);
  const deliver = useRef(onFix);
  deliver.current = onFix;

  function cancel() {
    epoch.current++;
    if (watch.current !== null) navigator.geolocation.clearWatch(watch.current);
    watch.current = null;
  }
  useEffect(() => () => cancel(), []);

  function stop() {
    cancel();
    setFollowing(false);
    setMessage("");
  }

  function locate(follow: boolean) {
    stop();
    const geo = navigator.geolocation;
    if (!geo) {
      setMessage("Location is unavailable. Search by address or parcel ID.");
      return;
    }
    const id = epoch.current;
    setFollowing(follow);
    setMessage("Finding your location…");
    let first = true;
    const received = ({ coords }: GeolocationPosition) => {
      if (id !== epoch.current) return;
      const next: LocationFix = {
        point: [coords.longitude, coords.latitude],
        accuracy: coords.accuracy,
      };
      setFix(next);
      setMessage("");
      deliver.current(next, first);
      first = false;
    };
    const failed = (error: GeolocationPositionError) => {
      if (id !== epoch.current) return;
      stop();
      setFix(null);
      setMessage(
        error.code === 1
          ? "Location permission was denied. Search by address or parcel ID."
          : "Location could not be determined. Try again or search by address.",
      );
    };
    const options = {
      enableHighAccuracy: true,
      timeout: 12000,
      maximumAge: 10000,
    };
    if (follow) watch.current = geo.watchPosition(received, failed, options);
    else geo.getCurrentPosition(received, failed, options);
  }
  return { fix, following, message, locate, stop };
}
