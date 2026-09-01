<?php

namespace App\Enums;

enum UserType: string
{
    case ADMIN = 'admin';
    case TESTER = 'tester';
    case OWNER = 'owner';

    public function label(): string
    {
        return match($this) {
            self::ADMIN => '관리자',
            self::TESTER => '테스터',
            self::OWNER => '소유자',
        };
    }

    public static function options(): array
    {
        return collect(self::cases())->mapWithKeys(fn ($type) => [
            $type->value => $type->label()
        ])->all();
    }
}
