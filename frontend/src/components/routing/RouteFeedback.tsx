import { useRouter, type ErrorComponentProps } from "@tanstack/react-router";

import { Button, Card, ExternalLink } from "../ui";
import { routeCopy as copy } from "./routeCopy";

export function RoutePending() {
  return <Card role="status">{copy.pending}</Card>;
}

export function RouteFailure({ reset }: ErrorComponentProps) {
  const router = useRouter();
  return (
    <Card role="alert" data-testid="route-error">
      <h1>{copy.failed}</h1>
      <p>{copy.recovery}</p>
      <Button onClick={() => void router.invalidate().then(reset)}>{copy.retry}</Button>
      <Button onClick={() => window.location.reload()}>{copy.reload}</Button>
    </Card>
  );
}

export function RouteMissing() {
  return (
    <Card data-testid="route-not-found">
      <h1>{copy.missing}</h1>
      <p>{copy.missingHelp}</p>
      <ExternalLink href="/">{copy.home}</ExternalLink>
    </Card>
  );
}
