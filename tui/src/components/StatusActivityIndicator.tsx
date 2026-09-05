/** Animated activity indicator for the status bar (scanner "eye" style).
 *
 * A bright braille block sweeps back and forth across a row of dim dots.
 * Braille glyphs (not solid blocks) keep the cell thin and match the
 * spinner's visual language. BRIGHT mirrors theme.running as RGB channels
 * because the interpolation needs numbers, not the token's hex string.
 */
import { useEffect, useRef, useState } from "react";

const BRAILLE_LEVELS = ["⠀", "⠁", "⠃", "⡇", "⣇", "⣷"] as const;

function toHex(red: number, green: number, blue: number): string {
    const clamp = (channel: number) =>
        Math.max(0, Math.min(255, Math.round(channel)));
    return (
        "#" +
        [clamp(red), clamp(green), clamp(blue)]
            .map((channel) => channel.toString(16).padStart(2, "0"))
            .join("")
    );
}

function mix(dim: [number, number, number], bright: [number, number, number], t: number): string {
    return toHex(
        dim[0] + (bright[0] - dim[0]) * t,
        dim[1] + (bright[1] - dim[1]) * t,
        dim[2] + (bright[2] - dim[2]) * t,
    );
}

const DIM: [number, number, number] = [70, 70, 80];
const BRIGHT: [number, number, number] = [210, 153, 34]; // theme.running #d29922

/** Renders nothing when idle; when running, a back-and-forth scanner sweep. */
export function StatusActivityIndicator({
    width = 10,
    speedMs = 55,
}: {
    width?: number;
    speedMs?: number;
}) {
    const [position, setPosition] = useState(0);
    const directionRef = useRef(1);

    useEffect(() => {
        const id = setInterval(() => {
            setPosition((previous) => {
                let next = previous + directionRef.current;
                if (next >= width - 1) {
                    next = width - 1;
                    directionRef.current = -1;
                } else if (next <= 0) {
                    next = 0;
                    directionRef.current = 1;
                }
                return next;
            });
        }, speedMs);
        return () => clearInterval(id);
    }, [width, speedMs]);

    const cells = [];
    for (let index = 0; index < width; index++) {
        const distance = Math.abs(index - position);
        let glyph: string = "·";
        let intensity = 0;
        if (distance === 0) {
            glyph = BRAILLE_LEVELS[5];
            intensity = 1;
        } else if (distance === 1) {
            glyph = BRAILLE_LEVELS[4];
            intensity = 0.55;
        } else if (distance === 2) {
            glyph = BRAILLE_LEVELS[2];
            intensity = 0.25;
        }
        cells.push(
            <span key={index} fg={mix(DIM, BRIGHT, intensity)}>
                {glyph}
            </span>,
        );
    }
    return <text>{cells}</text>;
}
