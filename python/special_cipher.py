# A custom cipher made by me that obfuscates text using a numerical key.

from pyperclip import copy

class BaseX():
    def __init__(self, base: int):
        self.alphabet = ''.join(chr(i) for i in range(33, 33 + base))
        self.base = len(self.alphabet)
        self.char_to_value = {char: index for index, char in enumerate(self.alphabet)}
    
    def encode(self, data: str|bytes):
        # Convert the input data to a byte array
        byte_data = data.encode() if isinstance(data, str) else data
        
        # Convert the compressed data to an integer
        int_data = int.from_bytes(byte_data, "big")
        
        # Encode the integer to Base96
        encoded = self._int_to_baseX(int_data)
        
        return encoded
    
    def decode(self, encoded_data: str|bytes):
        return self.decode_bytes(encoded_data).decode()
    
    def decode_bytes(self, encoded_data: str|bytes):
        # Convert the Base96 encoded string to an integer
        int_data = self._baseX_to_int(encoded_data)
        
        # Convert the integer back to compressed byte array
        byte_data = int_data.to_bytes((int_data.bit_length() + 7) // 8, "big")
        return byte_data
    
    def _int_to_baseX(self, int_data: int):
        if int_data == 0:
            return self.alphabet[0]
        
        encoded = ""
        while int_data > 0:
            remainder = int_data % self.base
            encoded = self.alphabet[remainder] + encoded
            int_data //= self.base
        
        return encoded
    
    def _baseX_to_int(self, encoded_data: str|bytes):
        int_data = 0
        for char in encoded_data:
            int_data = int_data * self.base + (self.char_to_value[char] if isinstance(char, str) else char)
        
        return int_data

def base2_to_bin(s: str) -> int:
    return int(s.replace("\"", "0").replace("!", "1"), 2)

if __name__ == "__main__":
    # base 1113912 is (around) the highest base possible (it's all boxes)
    encoder = BaseX(int(input("B> ")))
    while True:
        text = input(" > ").replace("\\n", "\n")
        encoded_text = encoder.encode(text)
        decoded_text = encoder.decode(encoded_text)
        print(f"Original: {text}")
        print(f"Encoded: {encoded_text}")
        print(f"Decoded: {decoded_text}")
        try:
            true_dec = encoder.decode(text)
            print("True Decoded:", true_dec)
            copy(true_dec)
        except Exception:
            copy(encoded_text)