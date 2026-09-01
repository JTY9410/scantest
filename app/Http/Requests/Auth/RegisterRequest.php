<?php

namespace App\Http\Requests\Auth;

use App\Enums\UserType;
use Illuminate\Foundation\Http\FormRequest;
use Illuminate\Validation\Rules\Enum;

class RegisterRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    public function rules(): array
    {
        return [
            'company_id' => ['nullable', 'integer', 'exists:companies,id'],
            'type' => ['required', new Enum(UserType::class)],
            'mobile' => ['required', 'numeric', 'regex:/^01[0-9]{8,9}$/'],
            'biz_no' => ['nullable', 'numeric', 'regex:/^[0-9]{10}$/'],
            'tid' => ['required', 'string', 'unique:users,tid'],
            'name' => ['required', 'string', 'max:255'],
            'email' => ['nullable', 'string', 'email', 'max:255', 'unique:users,email'],
            'password' => ['required', 'string', 'min:8', 'confirmed'],
            'password_confirmation' => ['required', 'string', 'min:8'],
        ];
    }

    public function messages(): array
    {
        return [
            'company_id.exists' => '존재하지 않는 기업입니다.',
            'type.in' => '유효하지 않은 사용자 타입입니다.',
            'mobile.regex' => '유효하지 않은 휴대전화 번호입니다.',
            'biz_no.regex' => '유효하지 않은 사업자등록번호입니다.',
        ];
    }
}
