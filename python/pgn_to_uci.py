# A PGN-to-UCI Chess notation converter written entirely in Python without any external libraries.
# Has a few kinks (namely with edge cases in niche moves) but handles all regular chess moves just fine.

def sqrt(x: float) -> float:
    return x ** 0.5

class PGNtoUCI():
    def __init__(self):
        self.board = [["r", "h", "b", "q", "k", "b", "h", "r"],
                      ["p", "p", "p", "p", "p", "p", "p", "p"],
                      [" ", " ", " ", " ", " ", " ", " ", " "],
                      [" ", " ", " ", " ", " ", " ", " ", " "],
                      [" ", " ", " ", " ", " ", " ", " ", " "],
                      [" ", " ", " ", " ", " ", " ", " ", " "],
                      ["P", "P", "P", "P", "P", "P", "P", "P"],
                      ["R", "H", "B", "Q", "K", "B", "H", "R"]]

        self.current_player = "White"

        self.castling = {
            "White": True,
            "Black": True
        }

        self.last_pawn_move = {
            "color": "None",
            "double": False,
            "end_pos": (0, 0)
        }

    def convert_to_coordinates(self, move: str):
        start_col, start_row, end_col, end_row = map(ord, move)
        start_col -= 97
        start_row = 8 - int(chr(start_row))
        end_col -= 97
        end_row = 8 - int(chr(end_row))
        return start_col, start_row, end_col, end_row

    def convert_to_algebraic(self, move: tuple):
        return f"{chr(move[0] + 97)}{8 - move[1]}{f'{chr(move[2] + 97)}{8 - move[3]}' if len(move) == 4 else ''}{str(move[(2 if len(move) != 4 else 4):]).replace('(', '').replace(')', '')}"

    def pgn_to_uci(self, pgn_move: str):
        pgn_move = pgn_move.replace("#", "").replace("+", "")

        piece = (
            "H"
            if pgn_move[0].upper() == "N" and pgn_move[0].isalpha() and pgn_move[1].isalpha()
            else pgn_move[0].upper()
            if pgn_move[0].isalpha() and pgn_move[1].isalpha()
            else "P"
        )

        destination = pgn_move[-2 - (2 if "=" in pgn_move else 0):(-2 if "=" in pgn_move else len(pgn_move))]
        promotion = "=" + pgn_move[-1].upper() if "=" in pgn_move else ""

        possible_starting_positions = []
        for row_idx, row in enumerate(self.board):
            for col_idx, value in enumerate(row):
                if value.upper() == piece:
                    possible_starting_positions.append((row_idx, col_idx))

        starting_position = None
        for position in possible_starting_positions:
            if self.is_valid_move(
                position[1],
                position[0],
                ord(destination[0]) - 97,
                8 - int(destination[1])
            ):
                starting_position = (position[0], position[1])
                break

        if starting_position:
            row = starting_position[1]
            col = starting_position[0]
            return self.convert_to_algebraic((row, col)) + destination + promotion

        return None

    def is_valid_move(self, start_col, start_row, end_col, end_row):
        piece = self.board[start_row][start_col]

        if start_col == end_col and start_row == end_row:
            return False

        if (piece == "P" and self.current_player == "White") or (piece == "p" and self.current_player == "Black"):
            if start_col == end_col:
                if (start_row == 6 and self.current_player == "White") or (start_row == 1 and self.current_player == "Black"):
                    if ((end_row == 4 or end_row == 5) and self.current_player == "White" and not self.get_obstruction_at(end_col, 5)) or \
                       ((end_row == 2 or end_row == 3) and self.current_player == "Black" and not self.get_obstruction_at(end_col, 2)) and \
                       self.get_obstruction_at(end_col, end_row) == False:
                        self.last_pawn_move["color"] = self.current_player
                        self.last_pawn_move["double"] = (end_row == 4 and self.current_player == "White") or (end_row == 3 and self.current_player == "Black")
                        self.last_pawn_move["end_pos"] = (end_row, end_col)
                        return True
                    return False
                elif end_row == start_row - 1 and self.get_obstruction_at(end_col, end_row) == False:
                    self.last_pawn_move["color"] = "White"
                    self.last_pawn_move["double"] = False
                    self.last_pawn_move["end_pos"] = (end_row, end_col)
                    return True
                return False
            elif (-2 < start_col - end_col < 2 and
                  ((end_row == start_row - 1 and self.current_player == "White") or
                   (end_row == start_row + 1 and self.current_player == "Black"))) and \
                 (self.get_obstruction_at(end_col, end_row) or
                  (end_row == self.last_pawn_move["end_pos"][0] + (-1 if self.current_player == "White" else 1) and
                   end_col == self.last_pawn_move["end_pos"][1] and
                   self.last_pawn_move["double"] and
                   self.last_pawn_move["color"] != self.current_player)):
                if end_row == self.last_pawn_move["end_pos"][0] + (-1 if self.current_player == "White" else 1):
                    self.clear_position(self.last_pawn_move["end_pos"][1], self.last_pawn_move["end_pos"][0])
                return True
            return False

        elif (piece == "R" and self.current_player == "White") or (piece == "r" and self.current_player == "Black"):
            if start_col == end_col or start_row == end_row:
                if not self.get_obstructions(start_col, start_row, end_col, end_row):
                    self.reset_move_data(True)
                    return True
            return False

        elif (piece == "H" and self.current_player == "White") or (piece == "h" and self.current_player == "Black"):
            if ((abs(start_col - end_col), abs(start_row - end_row)) in [(1, 2), (2, 1)]):
                self.reset_move_data()
                return True
            return False

        elif (piece == "B" and self.current_player == "White") or (piece == "b" and self.current_player == "Black"):
            if abs(start_col - end_col) == abs(start_row - end_row) and not self.get_obstructions(start_col, start_row, end_col, end_row):
                self.reset_move_data()
                return True
            return False

        elif (piece == "Q" and self.current_player == "White") or (piece == "q" and self.current_player == "Black"):
            if ((abs(start_col - end_col) == abs(start_row - end_row)) or
                (start_col == end_col or start_row == end_row)) and not self.get_obstructions(start_col, start_row, end_col, end_row):
                self.reset_move_data()
                return True
            return False

        elif (piece == "K" and self.current_player == "White") or (piece == "k" and self.current_player == "Black"):
            if abs(start_col - end_col) < 2 and abs(start_row - end_row) < 2:
                self.reset_move_data(True)
                return True
            return False

        return False

    def get_piece_at(self, col, row):
        return None if col > 7 or row > 7 else self.board[row][col] if self.board[row][col] != " " else None

    def get_obstruction_at(self, col, row):
        return self.get_piece_at(col, row) is not None

    def get_obstructions(self, start_col, start_row, end_col, end_row):
        dx = abs(end_col - start_col)
        dy = abs(end_row - start_row)
        sx = -1 if start_col > end_col else 1 if start_col != end_col else 0
        sy = -1 if start_row > end_row else 1 if start_row != end_row else 0
        cx, cy = start_col + sx, start_row + sy

        while (cx, cy) != (end_col, end_row):
            if self.get_obstruction_at(cx, cy):
                return True
            cx += sx
            cy += sy

        return False

    def clear_position(self, col, row):
        self.board[row][col] = " "

    def reset_move_data(self, reset_castling=False):
        self.last_pawn_move["color"] = "None"
        self.last_pawn_move["double"] = False
        self.last_pawn_move["end_pos"] = (0, 0)
        if reset_castling:
            self.castling[self.current_player] = False
    
    def move(self, m: str) -> str | None:
        uci_move = self.pgn_to_uci(m)
        if uci_move:
            start_col, start_row = ord(uci_move[0]) - 97, 8 - int(uci_move[1])
            end_col, end_row = ord(uci_move[2]) - 97, 8 - int(uci_move[3])
            self.board[end_row][end_col] = self.board[start_row][start_col]
            self.clear_position(start_col, start_row)
            self.current_player = "Black" if self.current_player == "White" else "White"
            return uci_move
        return None

conv = PGNtoUCI()

print(conv.move("e4"))     # e2e4
print(conv.move("e5"))     # e7e5
print(conv.move("Nf3"))    # g1f3
print(conv.move("Nc6"))    # b8c6
print(conv.move("Bb5"))    # f1b5