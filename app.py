import streamlit as st
import pandas as pd
import numpy as np
import joblib
import ast
from sklearn.metrics.pairwise import cosine_similarity

import logging

logging.basicConfig(level=logging.DEBUG)
print("Загружается приложение...")


def parse_list_column(x):
    if isinstance(x, str):
        try:
            return ast.literal_eval(x)
        except:
            return []
    return x


@st.cache_data
def load_data():
    print("Загружаются модель и данные")
    preprocessor = joblib.load("pkl/preprocessor.pkl")
    mlb_skills = joblib.load("pkl/mlb_skills.pkl")
    mlb_teacher = joblib.load("pkl/mlb_teacher.pkl")
    courses = pd.read_csv("courses-cleaned.csv")

    courses["skills"] = courses["skills"].apply(parse_list_column)
    courses["teacher"] = courses["teacher"].apply(parse_list_column)

    print("Все файлы загружены.")
    return preprocessor, mlb_skills, mlb_teacher, courses


def preprocess_courses_with_feature_ranges(
    courses, preprocessor, mlb_skills, mlb_teacher
):
    X_partial = preprocessor.transform(courses)
    if hasattr(X_partial, "toarray"):
        X_partial = X_partial.toarray()

    skills_encoded = mlb_skills.transform(courses["skills"])
    teacher_encoded = mlb_teacher.transform(courses["teacher"])

    X_final = np.hstack([X_partial, skills_encoded, teacher_encoded])

    cat_feature_count = (
        preprocessor.named_transformers_["cat"].categories_[0].shape[0]
        + preprocessor.named_transformers_["cat"].categories_[1].shape[0]
    )

    skills_feature_start = X_partial.shape[1]
    skills_feature_end = skills_feature_start + skills_encoded.shape[1]

    return X_final, cat_feature_count, skills_feature_start, skills_feature_end


def recommend_courses_cosine_weighted_filtered(
    user_input,
    preprocessor,
    mlb_skills,
    mlb_teacher,
    courses,
    X_final,
    cat_feature_count,
    skills_start,
    skills_end,
    weight_category=2,
    weight_skills=2,
    top_n=5,
):
    user_df = pd.DataFrame(
        [
            {
                "category": user_input.get("category", ""),
                "course_level": user_input.get("course_level", ""),
                "course_rating": user_input.get("course_rating", 0),
                "price": user_input.get("price", 0),
                "hpw": user_input.get("hpw", 0),
                "certificate_binary": 1 if user_input.get("certificate", False) else 0,
                "skills": user_input.get("skills", []),
                "teacher": user_input.get("teacher", []),
            }
        ]
    )

    X_partial = preprocessor.transform(user_df)
    if hasattr(X_partial, "toarray"):
        X_partial = X_partial.toarray()

    skills_encoded = mlb_skills.transform(user_df["skills"])
    teacher_encoded = mlb_teacher.transform(user_df["teacher"])

    user_vec = np.hstack([X_partial, skills_encoded, teacher_encoded])

    user_vec_weighted = user_vec.copy()
    X_final_weighted = X_final.copy()

    user_vec_weighted[:, :cat_feature_count] *= weight_category
    X_final_weighted[:, :cat_feature_count] *= weight_category

    user_vec_weighted[:, skills_start:skills_end] *= weight_skills
    X_final_weighted[:, skills_start:skills_end] *= weight_skills

    similarities = cosine_similarity(user_vec_weighted, X_final_weighted)[0]
    sorted_indices = similarities.argsort()[::-1]

    user_skills_set = set(user_input.get("skills", []))

    filtered_indices = []
    for idx in sorted_indices:
        course_skills = set(courses.iloc[idx]["skills"])
        if user_skills_set.intersection(course_skills):
            filtered_indices.append(idx)
        if len(filtered_indices) == top_n:
            break

    if len(filtered_indices) < top_n:
        for idx in sorted_indices:
            if idx not in filtered_indices:
                filtered_indices.append(idx)
            if len(filtered_indices) == top_n:
                break

    recommendations = courses.iloc[filtered_indices].copy()
    return recommendations.reset_index(drop=True)


def main():
    st.markdown(
        "<h1 style='text-align: center;'>🎓 Интеллектуальный помощник по подбору курсов</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        """
    <p style='text-align: center; font-size: 1.1rem'>
        Заполните фильтр ниже по критериям, которые подходят Вам и нажмите на кнопку "Рекомендовать" 🎯
    </p>
    """,
        unsafe_allow_html=True,
    )

    st.markdown("<hr style='margin: 2rem 0;'>", unsafe_allow_html=True)

    preprocessor, mlb_skills, mlb_teacher, courses = load_data()
    X_final, cat_feat_count, skills_start, skills_end = (
        preprocess_courses_with_feature_ranges(
            courses, preprocessor, mlb_skills, mlb_teacher
        )
    )

    category = st.selectbox(
        "Категория курса", sorted(courses["category"].dropna().unique())
    )
    course_level = st.selectbox(
        "Уровень курса", sorted(courses["course_level"].dropna().unique())
    )
    course_rating = st.slider("Желаемый рейтинг курса", 0.0, 5.0, 0.0, 0.1)
    price = st.number_input("Цена курса", min_value=0.0, value=0.0)
    hpw = st.slider("Часов в неделю", 0, 40, 2)
    certificate = st.checkbox("Сертификат", value=True)

    skills_options = sorted(
        set(skill for skills in courses["skills"] for skill in skills)
    )
    selected_skills = st.multiselect("Навыки", skills_options)

    teacher_options = sorted(
        set(t for teachers in courses["teacher"] for t in teachers)
    )
    selected_teachers = st.multiselect("Преподаватели (опционально)", teacher_options)

    if st.button("Рекомендовать"):
        user_input = {
            "category": category,
            "course_level": course_level,
            "course_rating": course_rating,
            "price": price,
            "hpw": hpw,
            "certificate": certificate,
            "skills": selected_skills,
            "teacher": selected_teachers,
        }

        recommendations = recommend_courses_cosine_weighted_filtered(
            user_input,
            preprocessor,
            mlb_skills,
            mlb_teacher,
            courses,
            X_final,
            cat_feat_count,
            skills_start,
            skills_end,
            weight_category=20,
            weight_skills=10,
            top_n=5,
        )

        st.subheader("📚 Рекомендуемые курсы:")
        for _, row in recommendations.iterrows():
            st.markdown(
                f"""
                <div class="recommendation-box">
                    <h3><a href="{row['course_link']}" target="_blank">{row['course_name']}</a></h3>
                    <p><strong>Категория:</strong> {row['category']}</p>
                    <p><strong>Навыки:</strong> {', '.join(row['skills'])}</p>
                    <p><strong>💰 Цена:</strong> {row['price']}</p>
                </div>
            """,
                unsafe_allow_html=True,
            )


if __name__ == "__main__":
    main()
