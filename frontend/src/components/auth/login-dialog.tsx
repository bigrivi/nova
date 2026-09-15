"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { clearAuthCredentials, setAuthCredentials } from "@/lib/auth";
import { probeAuth } from "@/lib/nova-api";

type LoginDialogProps = {
    open: boolean;
    onAuthenticated: () => void;
};

export function LoginDialog({ open, onAuthenticated }: LoginDialogProps) {
    const { t } = useTranslation();
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    async function handleSubmit(event: React.FormEvent) {
        event.preventDefault();
        if (busy) {
            return;
        }
        setBusy(true);
        setError(null);
        setAuthCredentials({ username, password });
        try {
            await probeAuth();
            setPassword("");
            onAuthenticated();
        } catch {
            clearAuthCredentials();
            setPassword("");
            setError(t("auth.error"));
        } finally {
            setBusy(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={() => {}}>
            <DialogContent showCloseButton={false} className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>{t("auth.title")}</DialogTitle>
                    <DialogDescription>
                        {t("auth.description")}
                    </DialogDescription>
                </DialogHeader>
                <form onSubmit={handleSubmit} className="flex flex-col gap-3">
                    <Input
                        autoFocus
                        value={username}
                        onChange={(event) => setUsername(event.target.value)}
                        placeholder={t("auth.username")}
                        aria-label={t("auth.username")}
                        disabled={busy}
                        required
                    />
                    <Input
                        type="password"
                        value={password}
                        onChange={(event) => setPassword(event.target.value)}
                        placeholder={t("auth.password")}
                        aria-label={t("auth.password")}
                        disabled={busy}
                        required
                    />
                    {error ? (
                        <p className="text-sm text-destructive">{error}</p>
                    ) : null}
                    <Button type="submit" disabled={busy}>
                        {t("auth.submit")}
                    </Button>
                </form>
            </DialogContent>
        </Dialog>
    );
}
