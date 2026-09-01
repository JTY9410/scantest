<?php

namespace App\Enums;

enum ScanType: string
{
    case EV = 'ev';
    case ICE = 'ice';

    public function label(): string
    {
        return match($this) {
            self::EV => '전기차',
            self::ICE => '내연기관',
        };
    }

    public function color(): string
    {
        return match($this) {
            self::EV => 'success',
            self::ICE => 'warning',
        };
    }

    public function code(): string
    {
        return match($this) {
            self::EV => 'EV',
            self::ICE => 'ICE',
        };
    }

    public static function options(): array
    {
        return collect(self::cases())->mapWithKeys(fn ($case) => [
            $case->value => $case->label()
        ])->all();
    }
}
