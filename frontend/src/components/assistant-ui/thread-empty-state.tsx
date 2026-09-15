import { useState, type FC, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

const GREETING_KEYS = [
    "app.welcomeGreeting1",
    "app.welcomeGreeting2",
    "app.welcomeGreeting3",
    "app.welcomeGreeting4",
    "app.welcomeGreeting5",
    "app.welcomeGreeting6",
    "app.welcomeGreeting7",
    "app.welcomeGreeting8",
] as const;

const Welcome: FC = () => {
    const { t } = useTranslation();
    const [greetingKey] = useState(
        () => GREETING_KEYS[Math.floor(Math.random() * GREETING_KEYS.length)],
    );

    return (
        <section className="mb-3 flex flex-col items-center text-center">
            <h1 className="text-3xl">{t(greetingKey)}</h1>
        </section>
    );
};

export const EmptyState: FC<{ children: ReactNode }> = ({ children }) => (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-6 md:px-4">
        <div className="flex w-full max-w-(--thread-max-width) flex-col items-stretch">
            <Welcome />
            {children}
        </div>
    </div>
);
