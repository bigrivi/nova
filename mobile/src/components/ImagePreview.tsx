import Feather from "@expo/vector-icons/Feather";
import {
    Image,
    Modal,
    Pressable,
    StyleSheet,
    View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

export function ImagePreview({
    uri,
    onClose,
}: {
    uri: string | null;
    onClose: () => void;
}) {
    const insets = useSafeAreaInsets();

    return (
        <Modal
            visible={uri !== null}
            transparent
            animationType="fade"
            onRequestClose={onClose}
        >
            <View style={styles.root}>
                {uri ? (
                    <Image
                        source={{ uri }}
                        style={styles.image}
                        resizeMode="contain"
                    />
                ) : null}
                <Pressable
                    onPress={onClose}
                    style={[styles.close, { top: insets.top + 12 }]}
                    accessibilityRole="button"
                    accessibilityLabel="Close image preview"
                >
                    <Feather name="x" size={20} color="#FFFFFF" />
                </Pressable>
            </View>
        </Modal>
    );
}

const styles = StyleSheet.create({
    root: {
        flex: 1,
        backgroundColor: "rgba(0,0,0,0.94)",
        alignItems: "center",
        justifyContent: "center",
    },
    image: {
        width: "100%",
        height: "100%",
    },
    close: {
        position: "absolute",
        right: 16,
        width: 36,
        height: 36,
        borderRadius: 18,
        backgroundColor: "rgba(255,255,255,0.16)",
        alignItems: "center",
        justifyContent: "center",
    },
});
